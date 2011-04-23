(ns calenderp.facebook
  (:require [clojure.string :as str])
  (:use [clojure.contrib.json :only [read-json]]
        [calenderp.config.config])
  (:import [org.apache.commons.codec.binary Base64]
           [javax.crypto Mac]
           [javax.crypto.spec SecretKeySpec]))

(defn hmac-sha-256
  "Returns a HMAC-SHA256 hash of the provided data."
  [^String key ^String data]
  (let [hmac-key (SecretKeySpec. (.getBytes key) "HmacSHA256")
        hmac (doto (Mac/getInstance "HmacSHA256") (.init hmac-key))]
    (String. (org.apache.commons.codec.binary.Base64/encodeBase64
              (.doFinal hmac (.getBytes data)))
             "UTF-8")))

(defn base64-decode [base64]
  "Decodes a base64 string, convenience wrapper around Java library."
  (String. (Base64/decodeBase64 base64)))

(defn decode-signed-request [signed-request key]
  "Takes a Facebook signed_request parameter and the applications secret
  key and returns a payload hash or nil if there was a problem."
  (when (and signed-request key)
    (let [[signiture payload] (str/split signed-request #"\.")
          signiture (str (str/replace signiture #"[_-]" "/") "=")]
      (when (= signiture (hmac-sha-256 key payload))
        (read-json (base64-decode payload))))))

(defn fb-auth-status [{signed-request "signed_request"}]
  (let [payload (decode-signed-request signed-request FACEBOOK-APP-SECRET)]
    (if payload
      {:connected? true :payload payload}
      {:connected? false})))