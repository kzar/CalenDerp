(ns calenderp.core
  (:require [appengine-magic.core :as ae]
            [net.cgrand.enlive-html :as html])
  (:use [net.cgrand.moustache :only [app]]
        [calenderp.utils]
        [calenderp.config.config]
        [calenderp.facebook :only [fb-auth-status]]
        [clj-facebook-graph.auth :only [decode-signed-request]]
        [calenderp.googlecal :only [demo-cal-create]]
        [clojure.contrib.json :only [json-str]]
        [ring.middleware.params :only [wrap-params]]
        [ring.util.response :only [redirect]]
        [ring.middleware.reload]))

(html/defsnippet css-include "calenderp/views/layout.html" [:head [:link (html/attr= :rel "stylesheet")]]
  [stylesheet]
  [:link] (html/set-attr :href stylesheet))

(html/defsnippet js-include "calenderp/views/layout.html" [:head [:script (html/nth-of-type 1)]]
  [js]
  [:script] (html/set-attr :src js))

(html/deftemplate layout "calenderp/views/layout.html"
  [{:keys [title content stylesheets js]}]
  #{[:title] [:#title]} (maybe-content title)
  [:head] (html/do->
           (html/append (map css-include stylesheets))
           (html/append (map js-include js)))
  [:#content] (maybe-substitute content))

(html/defsnippet testing-form "calenderp/views/test-page.html" [:#testing-form]
  [signed-request facebook-token google-token]
  [:#signed-request] (html/set-attr :value signed-request)
  [:#facebook-token] (html/set-attr :value facebook-token)
  [:#google-token] (html/set-attr :value google-token))

(defn testing-page [request]
  (let [signed-request TEST-SIGNED-REQUEST
        google-token TEST-GOOGLE-TOKEN]
    (render-to-response
     (layout {:title "Calenderp testing page" :stylesheets ["/css/test.css"] :js ["/js/test.js"]
              :content (testing-form signed-request "" google-token)}))))

(defn home-page [request]
  (let [status (fb-auth-status (:params request))]
    (if (:connected? status)
      (render-to-response
       (layout {:title "Status Page" :content status}))
      (render-to-response
       (layout {:title "Install Page" :content status})))))

(defn signed-request-json [request signed-request]
  (render-to-response
   (let [decoded (decode-signed-request signed-request FACEBOOK-APP-SECRET)]
     (json-str decoded))))

(defn facebook-birthdays-json [request facebook-token]
  (render-to-response
   (let [birthdays (calenderp.facebook/friends {:oauth_token facebook-token})]
     (json-str birthdays))))

(defn facebook-events-json [request facebook-token]
  (render-to-response
   (let [events (calenderp.facebook/events {:oauth_token facebook-token})]
     (json-str events))))

(defn google-cal-test-json [request google-token]
  (render-to-response
    (calenderp.googlecal/demo-cal-create google-token)))

(def calenderp-app-handler
  (app
   wrap-params
   [""] (case (ae/appengine-environment-type)
              :interactive testing-page
              :dev-appserver testing-page
              :production home-page)
   ["ajax" "decode-signed-request" signed-request] #(signed-request-json % signed-request)
   ["ajax" "facebook-birthdays" facebook-token] #(facebook-birthdays-json % facebook-token)
   ["ajax" "facebook-events" facebook-token] #(facebook-events-json % facebook-token)
   ["ajax" "google-cal-test" google-token] #(google-cal-test-json % google-token)))

(ae/def-appengine-app calenderp-app
  (wrap-reload #'calenderp-app-handler '(calenderp.core)))

;(ae/def-appengine-app calenderp-app #'calenderp-app-handler)