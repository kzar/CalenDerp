(ns calenderp.facebook
  (:require [clojure.string :as str]
            [clj-facebook-graph.client :as client])
  (:use [clojure.contrib.json :only [read-json]]
        [calenderp.config.config]
        [calenderp.utils :only [ignore-exceptions]]
        [clj-facebook-graph.auth :only [facebook-auth-url with-facebook-auth]])
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

(defn base64-decode
  "Decodes a base64 string, convenience wrapper around Java library."
  [base64]
  (String. (Base64/decodeBase64 base64)))

(defn strtr
  "My take on PHP's strtr function."
  [value from to]
  ((apply comp (map (fn [a b] #(.replace % a b)) from to))
   value))

(defn decode-signed-request
  "Takes a Facebook signed_request parameter and the applications secret
  key and returns a payload hash or nil if there was a problem."
  [signed-request key]
  (when (and signed-request key
             (re-matches #"^[^\.]+\.[^\.]+$" signed-request))
    (let [[signiture payload] (str/split signed-request #"\.")
          signiture (str (strtr signiture "-_" "+/") "=")]
      (when (= signiture (hmac-sha-256 key payload))
        (read-json (base64-decode payload))))))

(defn friends [{token :oauth_token}]
  (with-facebook-auth {:access-token token}
    (ignore-exceptions
     (client/get [:me :friends] {:query-parameters {:fields [:link :birthday :name :picture]} :extract :data}))))

;; FIXME - fields not passed properly :(

(defn fb-auth-status [{signed-request "signed_request"}]
  (let [payload (decode-signed-request signed-request FACEBOOK-APP-SECRET)]
    (if payload
      {:connected? true :payload payload :friends (friends payload)}
      {:connected? false})))