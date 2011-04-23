(ns calenderp.test.core
  (:use [calenderp.core])
  (:use [clojure.test])
  (:require [appengine-magic.testing :as ae-testing]))

(use-fixtures :each (ae-testing/local-services :all))

(deftest replace-me ;; FIXME: write
  (is false "No tests have been written."))
