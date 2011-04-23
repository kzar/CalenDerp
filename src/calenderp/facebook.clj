(ns calenderp.facebook
  (:use [clojure.contrib.string :only [split]]
        [clojure.contrib.json :only [read-json]]
        [calenderp.config.config])
  (:import [org.apache.commons.codec.binary Base64]
           [javax.crypto Mac]
           [javax.crypto.spec SecretKeySpec]))

(defn hmac-sha-256
  [^String key ^String data]
  (let [hmac-key (SecretKeySpec. (.getBytes key) "HmacSHA256")
        hmac (doto (Mac/getInstance "HmacSHA256") (.init hmac-key))]
    (String. (org.apache.commons.codec.binary.Base64/encodeBase64
              (.doFinal hmac (.getBytes data)))
             "UTF-8")))

(defn base64-decode [base64]
  (String. (Base64/decodeBase64 base64)))

(defn decode-signed-request [signed-request key]
  (when (and signed-request key)
    (let [[signiture payload] (split #"\." signed-request)]
      (when (= signiture (hmac-sha-256 key payload))
        (read-json (base64-decode payload))))))

(defn fb-auth-status [{signed-request "signed_request"}]
  (let [payload (decode-signed-request signed-request FACEBOOK-APP-SECRET)]
    (if payload
      {:connected? true :payload payload}
      {:connected? false})))

"o8E2NSAlRrQAheb_1LtcUxIg86F_Z4mJCit2wq_s2r8"

(hmac-sha-256 FACEBOOK-APP-SECRET "eyJhbGdvcml0aG0iOiJITUFDLVNIQTI1NiIsImV4cGlyZXMiOjAsImlzc3VlZF9hdCI6MTMwMzU5MjE4MSwib2F1dGhfdG9rZW4iOiIxNTMzNjgyNjEzNjU1ODJ8YzQ4Yzg2MzllN2EzZmZkMjVjMjExMTI3LjEtNTMxMTM1MDAwfGp0Ump3d2dHOWhNYVZ1cGVwTXRPQm9jZkl4QSIsInVzZXIiOnsiY291bnRyeSI6ImdiIiwibG9jYWxlIjoiZW5fR0IiLCJhZ2UiOnsibWluIjoyMX19LCJ1c2VyX2lkIjoiNTMxMTM1MDAwIn0")