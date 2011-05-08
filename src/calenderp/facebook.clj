(ns calenderp.facebook
  (:require [clojure.string :as str]
            [clj-facebook-graph.client :as client])
  (:use [clojure.contrib.json :only [read-json]]
        [calenderp.config.config]
        [calenderp.utils :only [ignore-exceptions]]
        [clj-facebook-graph.auth :only [facebook-auth-url with-facebook-auth]]
        [clj-time.format :only [parse formatter]]
        [clj-facebook-graph.auth :only [decode-signed-request]]))

(def facebook-birthday-formatter (formatter "MM/dd/yyyy"))
; Decode event date - (parse "2011-07-17T01:00:00+0000")
; Decode birthday date - (parse facebook-birthday-formatter "04/14/1984")

(defn friends [{token :oauth_token}]
  (with-facebook-auth {:access-token token}
    (ignore-exceptions
     (client/get [:me :friends] {:query-params {:fields "link,birthday,name,picture"} :extract :data}))))

(defn events [{token :oauth_token}]
  (with-facebook-auth {:access-token token}
    (ignore-exceptions
     (concat
      (take 20 (client/get [:me :events :attending] {:extract :data :paging true}))
      (take 20 (client/get [:me :events :maybe] {:extract :data :paging true}))))))
; FIXME - why limit to 20? 25 is page size, all is ideal but that requires more requests.


(defn fb-auth-status [{signed-request "signed_request"}]
  (let [payload (decode-signed-request signed-request FACEBOOK-APP-SECRET)]
    (if payload
      {:connected? true :payload payload :friends (friends payload)}
      {:connected? false})))