(ns calenderp.googlecal
  (:use [calenderp.config.config]
        [clj-time.core :only [date-time now plus days]]
        [clojure.contrib.seq-utils :only [indexed]])
  (:require [clojure.contrib.string :as str])
  (:import [com.google.gdata.client.calendar CalendarService]
           [com.google.gdata.client.authn.oauth OAuthParameters]
           [com.google.gdata.data.calendar CalendarEntry CalendarEventEntry CalendarEventFeed CalendarFeed ColorProperty HiddenProperty TimeZoneProperty]
           [com.google.gdata.data DateTime Link ILink$Rel ILink$Type PlainTextConstruct]
           [com.google.gdata.data.batch BatchOperationType BatchUtils]
           [com.google.gdata.data.extensions When]
           [java.net URL]))

(def *calendar-url* (URL. "https://www.google.com/calendar/feeds/default/owncalendars/full"))

(def batch-types {:query BatchOperationType/QUERY
                  :insert BatchOperationType/INSERT
                  :update BatchOperationType/UPDATE
                  :delete BatchOperationType/DELETE})

(defn calendar-service [token]
  (let [cs (CalendarService. "Calenderp")]
    (.setAuthSubToken cs token)
    cs))

(defn create-calendar [name description]
  {:action (doto (CalendarEntry.)
             (.setTitle (PlainTextConstruct. name))
             (.setSummary (PlainTextConstruct. description))
             (.setTimeZone (TimeZoneProperty. "UTC"))
             (.setHidden (HiddenProperty. "false"))
             (.setColor (ColorProperty. "#2952A3")))
   :type :insert
   :url *calendar-url*})

(defn calendar-url [calendar]
  (URL. (.getUri (.getContent calendar))))

(defn create-event [calendar name description start end]
  (let [start-end (doto (When.)
                    (.setStartTime (DateTime. (.getMillis start)))
                    (.setEndTime (DateTime. (.getMillis end))))]
    {:action (doto (CalendarEventEntry.)
               (.setTitle (PlainTextConstruct. name))
               (.setContent (PlainTextConstruct. description))
               (.addTime start-end))
     :type :insert
     :url calendar}))

(defn process-action [cs action]
  (case (:type action)
        :insert (.insert cs (:url action) (:action action))
        :update (.update cs (:url action) (:action action))
        :query (.query cs (:url action) (:action action))
        :delete (.delete cs (:url action) (:action action))))

(defn class->symbol
  ([class] (class->symbol class nil))
  ([class local?]
     (let [name (.getName class)]
       (symbol
        (if local? (last (str/split #"\." name)) name)))))

(defn action-status [result]
  (case (class->symbol (class result) true)
        CalendarEntry {:success true :calendar result}
        CalendarEventEntry (let [status (BatchUtils/getBatchStatus result)]
                             {:batch-id (BatchUtils/getBatchId result)
                              :success (.getReason status)
                              :message (.getContent status)
                              :title (.getText (.getTitle result))})))

(defn process-batch [cs batch]
  (let [url (:url (first batch))
        batch-request (CalendarEventFeed.)
        feed (.getFeed cs url CalendarEventFeed)
        batch-link (when (> (count batch) 1)
                    (.getLink feed ILink$Rel/FEED_BATCH ILink$Type/ATOM))]
    (map action-status
         (if batch-link
           (do
             (doseq [[i action] (indexed batch)]
               (BatchUtils/setBatchId (:action action) (str i))
               (BatchUtils/setBatchOperationType (:action action)
                                                 (batch-types (:type action)))
               (.add (.getEntries batch-request) (:action action)))
             (.getEntries (.batch cs (URL. (.getHref batch-link)) batch-request)))
           (doall (map (partial process-action cs) batch))))))

(defn process-batches [cs actions]
   (let [batches (partition-by :url actions)]
     (apply concat
            (doall (map (partial process-batch cs) batches)))))

(defn demo-cal-create [token]
  (let [cs (calendar-service token)
        result (process-batches cs [(create-calendar "test" "description")])
        calendar (calendar-url (:calendar (first result)))]
    (process-batches cs
                     (for [i (range 5)]
                       (create-event calendar (str "Test event " i) "yo"
                                     (now)
                                     (plus (now) (days 1)))))))
; Think..
;  - Add event creation tasks before calendar exists?
;  - Return results in same order as tasks given?
;  - How is queue handled without appengine?

