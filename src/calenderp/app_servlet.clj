(ns calenderp.app_servlet
  (:gen-class :extends javax.servlet.http.HttpServlet)
  (:use calenderp.core)
  (:use [appengine-magic.servlet :only [make-servlet-service-method]]))


(defn -service [this request response]
  ((make-servlet-service-method calenderp-app) this request response))
