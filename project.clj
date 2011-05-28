(defproject calenderp "0.0.1-SNAPSHOT"
  :description "Google calendar to facebook sync."
  :dependencies [[org.clojure/clojure "1.2.1"]
                 [net.cgrand/moustache "1.0.0"]
                 [enlive "1.0.0-SNAPSHOT"]
                 [clj-facebook-graph "0.2.0"]
                 [clj-time "0.3.0"]
                 [com.google.gdata/gdata-calendar-2.0 "1.41.5"]
                 [ring/ring-jetty-adapter "0.3.7"]]
  :dev-dependencies [[swank-clojure "1.3.0-SNAPSHOT"]
                     [ring/ring-devel "0.3.7"]]
  :repositories {"mandubian-mvn" "http://mandubian-mvn.googlecode.com/svn/trunk/mandubian-mvn/repository"})
