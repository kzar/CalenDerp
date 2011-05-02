(defproject calenderp "0.0.1-SNAPSHOT"
  :description "Google calendar to facebook sync."
  :dependencies [[org.clojure/clojure "1.2.1"]
                 [net.cgrand/moustache "1.0.0"]
                 [enlive "1.0.0-SNAPSHOT"]
                 [clj-facebook-graph "0.2.0"]
                 [clj-time "0.3.0"]]
  :dev-dependencies [[appengine-magic "0.4.1"]
                     [swank-clojure "1.3.0-SNAPSHOT"]
                     [ring/ring-devel "0.3.7"]])
