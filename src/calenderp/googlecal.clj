(ns calenderp.googlecal
  (:use [calenderp.config.config]
        [clj-time.core :only [date-time]]
        [clojure.contrib.seq-utils :only [indexed]])
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

(defn process-batch [cs batch]
  (let [url (:url (first batch))
        batch-request (CalendarEventFeed.)
        feed (.getFeed cs url CalendarEventFeed)
        batch-link (when (> (count batch) 1)
                    (.getLink feed ILink$Rel/FEED_BATCH ILink$Type/ATOM))]
    (if batch-link
      (do
        (doseq [[i action] (indexed batch)]
          (BatchUtils/setBatchId (:action action) (str i))
          (BatchUtils/setBatchOperationType (:action action)
                                            (batch-types (:type action)))
          (.add (.getEntries batch-request) (:action action)))
        (.batch cs (URL. (.getHref batch-link)) batch-request))
      (doall (map (partial process-action cs) batch)))))

(defn process-batches [cs actions]
  (let [batches (partition-by :url actions)]
    (apply concat (doall (map (partial process-batch cs) batches)))))

(let [cs (calendar-service TEST-GOOGLE-TOKEN)
      result (process-batches cs [(create-calendar "test" "description")])
      calendar (URL. (.getUri (.getContent (first result))))]
  (process-batches cs (repeat 5 (create-event calendar "Test event" "yo"
                                              (date-time 2011 4 8)
                                              (date-time 2011 4 9)))))