(ns calenderp.utils
  (:require [appengine-magic.core :as ae]
            [net.cgrand.enlive-html :as html])
  (:use [ring.util.response :only [response file-response]]))

(defn render [t]
  (apply str t))

(defn render-snippet [s]
  (apply str (html/emit* s)))

(def render-to-response
     (comp response render))

(defmacro maybe-substitute
  ([expr] `(if-let [x# ~expr] (html/substitute x#) identity))
  ([expr & exprs] `(maybe-substitute (or ~expr ~@exprs))))

(defmacro maybe-content
  ([expr] `(if-let [x# ~expr] (html/content x#) identity))
  ([expr & exprs] `(maybe-content (or ~expr ~@exprs))))