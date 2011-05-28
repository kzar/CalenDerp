(ns calenderp.core
  (:require [net.cgrand.enlive-html :as html]
            [calenderp.facebook :as fb])
  (:use [net.cgrand.moustache :only [app]]
        [calenderp.utils]
        [calenderp.config.config]
        [clj-facebook-graph.auth :only [decode-signed-request]]
        [calenderp.googlecal :only [demo-cal-create]]
        [clojure.contrib.json :only [json-str]]
        [ring.middleware.params :only [wrap-params]]
        [ring.util.response :only [redirect]]
        [ring.middleware.file :only [wrap-file]]
        [ring.adapter.jetty :only [run-jetty]]
        [ring.middleware.reload]))

(html/defsnippet css-include "templates/layout.html" [:head [:link (html/attr= :rel "stylesheet")]]
  [stylesheet]
  [:link] (html/set-attr :href stylesheet))

(html/defsnippet js-include "templates/layout.html" [:head [:script (html/nth-of-type 1)]]
  [js]
  [:script] (html/set-attr :src js))

(html/deftemplate layout "templates/layout.html"
  [{:keys [title content stylesheets js]}]
  #{[:title] [:#title]} (maybe-content title)
  [:head] (html/do->
           (html/append (map css-include stylesheets))
           (html/append (map js-include js)))
  [:#content] (maybe-substitute content))

(html/defsnippet testing-form "templates/test-page.html" [:#testing-form]
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
  (let [status (fb/fb-auth-status (:params request))]
    (if (:connected? status)
      (render-to-response
       (layout {:title "Status Page" :content status}))
      (render-to-response
       (layout {:title "Install Page" :content status})))))

(defn json-page [f & params]
  (fn [_] (render-to-response (json-str (apply f params)))))

(def calenderp-app-handler
  (app
   (wrap-reload '(calenderp.core))
   (wrap-file "static")
   wrap-params
   [""] home-page
   ["test"] testing-page
   ["ajax" "decode-signed-request" signed-request] (json-page decode-signed-request
                                                              signed-request FACEBOOK-APP-SECRET)
   ["ajax" "facebook-birthdays" facebook-token] (json-page fb/friends {:oauth_token facebook-token})
   ["ajax" "facebook-events" facebook-token] (json-page fb/events {:oauth_token facebook-token})
   ["ajax" "google-cal-test" google-token] (json-page demo-cal-create google-token)))

(defonce server
  (run-jetty #'calenderp-app-handler
             {:port 8080 :join? false}))

; (.stop server) (.start server)