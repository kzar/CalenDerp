from google.appengine.ext import db

class Users(db.Model):
  facebook_id = db.StringProperty(required=True)
  facebook_token = db.StringProperty()
  google_token = db.StringProperty()
  bday_cal = db.LinkProperty()
  event_cal = db.LinkProperty()
  events = db.TextProperty()
  birthdays = db.TextProperty()
  status = db.StringProperty(required=True)
  locale = db.StringProperty()
  time_difference = db.FloatProperty()

class Flags(db.Model):
  flag_key = db.StringProperty(required=True)
  value = db.StringProperty(required=True)

class TaskData(db.Model):
  data = db.TextProperty(required=True)
