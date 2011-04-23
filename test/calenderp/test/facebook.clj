(ns calenderp.test.facebook
  (:use [calenderp.facebook])
  (:use [clojure.test]))

(deftest hmac-sha-256-test
  (let [example "Mvq8XaiwC0gceHL5+4GF0xBeYZJu1uWk7bX5WQ6mvQ8="]
    (is (= example (hmac-sha-256 "test" "example message")) "Hashes correctly")))

(deftest decode-signed-request-test
  (let [example "vlXgu64BQGFSQrY0ZcJBZASMvYvTHu9GQ0YM9rjPSso.eyJhbGdvcml0aG0iOiJITUFDLVNIQTI1NiIsIjAiOiJwYXlsb2FkIn0"]
    (is (= {:algorithm "HMAC-SHA256" :0 "payload"} (decode-signed-request example "secret"))
        "Decodes correctly signed payload")
    (is (= nil (decode-signed-request example "wrong-secret"))
        "Discards payload with wrong signiture")))