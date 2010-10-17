import os, sys, re, facebook, logging
from google.appengine.api import users, urlfetch
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.api.urlfetch import DownloadError
from datetime import datetime
from uuid import uuid4

# Stuff for Google calendar
sys.path.insert(0, 'gdata.zip/gdata')
try:
  from xml.etree import ElementTree # for Python 2.5 users
except ImportError:
  from elementtree import ElementTree
import gdata.calendar.service
from gdata.service import NonAuthSubToken
import gdata.service
import atom.service
import gdata.calendar
import atom
import getopt
import sys
import string
import time


sys.path.insert(0, 'icalendar.zip')
import icalendar as ical

FACEBOOK_APP_ID = "xXxXxXxXxXx"
FACEBOOK_APP_SECRET = "xXxXxXxXxXx"

class Users(db.Model):
  email = db.StringProperty(required=True)
  facebook_id = db.StringProperty(required=True)
  facebook_token = db.StringProperty(required=True)
  google_token = db.StringProperty(required=True)

class Feed(db.Model):
  user_id = db.StringProperty(required=True)
  feed_id = db.StringProperty(required=True)
  auth_token = db.StringProperty(required=True)
  feed_type = db.StringProperty(required=True, choices=set(["birthdays", "events"]))

def render_birthday_feed(the_feed):
  """
  This does all the magic, takes the feed object and returns a nice iCal file.
  """
  # Set things up
  cal = ical.Calendar()
  date_regexp = re.compile("^([0-9]+)/([0-9]+)/?([0-9]*)$")
    
  # Run the facebook query
  graph = facebook.GraphAPI(the_feed.auth_token)
  try:
    results = graph.get_object("me/friends", fields="link,birthday,name,picture")
  except DownloadError:
    return

  if results and isinstance(results, dict) and results.has_key('data'):
    # Loop through results creating the ical object
    for friend in results['data']:
      r = date_regexp.search(friend.get('birthday', ''))
        
      if r:
        day = int(r.groups()[1])
        month = int(r.groups()[0])
        year = datetime.today().year
        title = friend['name'] + '\'s birthday!'
          
        # Check for dodgy dates
        try:
          datetime(year, month,day)
        except ValueError:
          logging.debug("Invalid date: " + str(day) + "/" + str(month) + "/" + str(year))
          continue

        entry = ical.Event()
        entry.add('summary', title)
        entry.add('dtstart', datetime(year, month, day, 9, 0, tzinfo=ical.UTC))
        entry.add('dten', datetime(year, month, day, 17, 0, tzinfo=ical.UTC))
#                entry.add('x-google-calendar-content-title', title)
        entry.add('x-google-calendar-content-icon', friend['picture'])
#                entry.add('x-google-calendar-content-url', friend['picture'])
#                entry.add('x-google-calendar-content-type', 'image')
#                entry.add('x-google-calendar-content-width', 50)
#                entry.add('x-google-calendar-content-height', 50)
                #entry.add('x-google-calendar-content-url', friend['link'])
                
        cal.add_component(entry)
      else:
        # No results, we probably need to resync.
        # Return a ical file that gives the user a clue..
        day = datetime.now().day
        month = datetime.now().month
        year = datetime.now().year

        entry = ical.Event()
        entry.add('summary', "Deerrrrrpp out-of-sync with Facebook! Go to http://apps.facebook.com/calenderp/ and it should start working again")
        entry.add('dtstart', datetime(year, month, day, 9, 0, tzinfo=ical.UTC))
        entry.add('dten', datetime(year, month, day, 17, 0, tzinfo=ical.UTC))
        cal.add_component(entry)
        
  return cal.as_string()

def GetAuthSubUrl(url):
  #url = 'http://calenderp.appspot.com'
  scope = 'http://www.google.com/calendar/feeds/'
  secure = False
  session = True
  calendar_service = gdata.calendar.service.CalendarService()
  return calendar_service.GenerateAuthSubURL(url, scope, secure, session);

def check_google_token(token):
  """Check with google if a token is valid. If so return the
  calendar service, if not return None"""
  calendar_service = gdata.calendar.service.CalendarService()
  calendar_service.SetAuthSubToken(token)
  try:
    calendar_service.AuthSubTokenInfo()
  except NonAuthSubToken:
    return None
  else:
    return calendar_service

def upgrade_google_token(token):
  """Take a token string that google gave us and upgrade it
  to a useable session one. Return the calendar object or None"""
  calendar_service = gdata.calendar.service.CalendarService()
  calendar_service.SetAuthSubToken(token)
  calendar_service.UpgradeToSessionToken()
  return (calendar_service)

def grab_google(facebook_id, email, facebook_token, token_param):
  """Firstly check the database for this user, see if they have a working
  token.
  
  If not check the token parameter, upgrade that to a nice session token
  and store it in the database.

  Return the calendar object or None if there are no working tokens."""
  # First check the database
  user = Users.all().filter("facebook_id =", facebook_id)
  if user.count():
    # Already registered, make sure token is valid
    calendar_service = check_google_token(user[0].google_token)
    
    if calendar_service:
      # Great we're done
      return calendar_service
    
  # No joy? Let's check the parameter
  if token_param:
    calendar_service = upgrade_google_token(token_param)

    if calendar_service:
      # Record the token in our database
      user = Users(email=email,
                   facebook_id=facebook_id,
                   facebook_token=facebook_token,
                   google_token=calendar_service.GetAuthSubToken())
      user.put()
      # Great a new user's first time
      return calendar_service

class gcal(webapp.RequestHandler):
  def get(self):
    # Set my userid for now
    facebook_id = 'dave'
    email = 'kzar@kzar.co.uk'
    facebook_token = 'blablah'
    calendar = grab_google(facebook_id, email, 
                           facebook_token, self.request.get("token"))

    if calendar:
      feed = calendar.GetCalendarListFeed()
      for i, a_calendar in enumerate(feed.entry):
        print '\t%s. %s' % (i, a_calendar.title.text,)
    else:
      self.response.out.write('<a href="%s">Login to your Google account</a>' % 
                              GetAuthSubUrl(self.request.url))      
      
## TODO http://code.google.com/apis/calendar/data/1.0/developers_guide_python.html#AuthAuthSub

class wishes(webapp.RequestHandler):
  def get(self):
    # Grab the friend's details
    friend_ID = self.request.get("id")

    graph = facebook.GraphAPI(self.current_user.access_token)
    friend = graph.get_object(friend_ID, type="large", fields="id,name,picture,birthday")

    path = os.path.join(os.path.dirname(__file__), 'wishes.html')
    args = dict(friend=friend)
    self.response.out.write(template.render(path, args))
  def post(self):
    target = self.request.get("id")
    message = self.request.get("msg")
    #result = fbauth.query(target + '/feed?message=' + message, self.current_user.access_token)
    graph = facebook.GraphAPI(self.current_user.access_token)
    graph.put_wall_post("API test message")
    self.response.out.write(result)

def new_feed_id():
  return str(uuid4())

def gimme_my_feeds(user_id, auth_token):
  # Grab their existing feeds
  feeds = Feed.all().filter("user_id =", user_id)
    
  if feeds.count():
    # Make sure they all have the newest token
    for feed in feeds:
      if feed.auth_token != auth_token:
        feed.auth_token = auth_token
        feed.put()
  else:
    # They don't have any, let's make 'um one!
    feed = Feed(user_id=user_id,
                feed_id=new_feed_id(),
                auth_token=auth_token,
                feed_type="birthdays")
    feed.put()

    # FIXME, this will return only the last feed
    # for the user if they have more than one.
  return feed
    
class MainPage(webapp.RequestHandler):
  def get(self):
    # Grab the auth_token from facebook's canvas magic
    token = facebook.oauth_token(self.request.get("signed_request"), FACEBOOK_APP_SECRET)

    # Let's see if they're authed        
    if token:
      # They are authed, grab their details and render settings page
      graph = facebook.GraphAPI(token)
      me = graph.get_object("me", type="large", fields="id,name,picture,birthday")
      args = {'me': me, 'feed': gimme_my_feeds(me['id'], token)}
      page = 'settings.html'
    else:
      # No dice, show them the install button and some convincing copy..
      args = {'install_link': facebook.oauth_URL(client_id=FACEBOOK_APP_ID, 
                                                 redirect_uri="http://apps.facebook.com/calenderp/",
                                                 display="page", scope="offline_access,friends_birthday")}
      page = 'install.html' 

      # Render the page :)
      path = os.path.join(os.path.dirname(__file__), page);
      self.response.out.write(template.render(path, args))

def render_error_feed(message):
  cal = ical.Calendar()

  day = datetime.now().day
  month = datetime.now().month
  year = datetime.now().year

  entry = ical.Event()
  entry.add('summary', "Deerrrrrpp out-of-sync with Facebook! ... " + message)
  entry.add('dtstart', datetime(year, month, day, 9, 0, tzinfo=ical.UTC))
  entry.add('dten', datetime(year, month, day, 17, 0, tzinfo=ical.UTC))
  cal.add_component(entry)
    
  return cal.as_string()

class view_feed(webapp.RequestHandler):
  def get(self, *ar):
    feeds = Feed.all().filter("feed_id =", ar[0]).fetch(1)

    self.response.headers["Content-Type"] = "text/calendar; charset=utf-8"
        
    if feeds:
      # This really is a feed in the database
      the_feed = feeds[0]

      # Birthday feed
      if the_feed.feed_type == "birthdays":
        bday_feed = render_birthday_feed(the_feed)
        if bday_feed:
          self.response.out.write(bday_feed)
          logging.info("Rendering bithdays feed.")
        else:
          self.error(504)
          logging.error("Connection to Facebook API failed, can't serve their ical :(")
      else:
        # Unknown feed type
        self.response.out.write(render_error_feed("This feed type is unknown. Email Dave, something's wrong"))
        logging.error("Invalid feed type: " + the_feed.feed_type)
    else:
      # Non-existant feed id
      self.response.out.write(render_error_feed("This feed link is wrong, go back and copy the link again."))
      logging.debug("Invalid feed link used.")
