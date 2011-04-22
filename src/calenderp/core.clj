(ns calenderp.core
  (:require [appengine-magic.core :as ae]
            [net.cgrand.enlive-html :as html])
  (:use [net.cgrand.moustache :only [app]]
        [calenderp.utils :only [maybe-content render-to-response]]
        [ring.middleware.reload]))

(html/deftemplate layout "calenderp/templates/layout.html"
  [{:keys [title content]}]
  [:#title] (maybe-content title)
  [:#content] (html/substitute content))

(def calenderp-app-handler
  (app
   [""] (fn [req] (render-to-response
                   (layout {})))
   ["test"] (fn [req] (render-to-response
                       (layout {:content "This is the test content!"})))))

;(ae/def-appengine-app calenderp-app
;  (wrap-reload #'calenderp-app-handler '(calenderp.core)))

(ae/def-appengine-app calenderp-app #'calenderp-app-handler)