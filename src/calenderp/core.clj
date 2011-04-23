(ns calenderp.core
  (:require [appengine-magic.core :as ae]
            [net.cgrand.enlive-html :as html])
  (:use [net.cgrand.moustache :only [app]]
        [calenderp.utils]
        [calenderp.facebook :only [fb-auth-status]]
        [ring.middleware.params :only [wrap-params]]
        [ring.util.response :only [redirect]]
        [ring.middleware.reload]))

(html/deftemplate layout "calenderp/views/layout.html"
  [{:keys [title content]}]
  [:#title] (maybe-content title)
  [:#content] (maybe-substitute content))

(defn status-page [status]
  (layout {:title "Status Page" :content status}))

(defn install-page [status]
  (layout {:title "Install Page" :content status}))

(def calenderp-app-handler
  (app
   wrap-params
   [""] (fn [req]
          (let [status (fb-auth-status (:params req))]
            (if (:connected? status)
              (render-to-response
               (status-page status))
              (render-to-response
               (install-page status)))))))

(ae/def-appengine-app calenderp-app
  (wrap-reload #'calenderp-app-handler '(calenderp.core)))

;(ae/def-appengine-app calenderp-app #'calenderp-app-handler)