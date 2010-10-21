import os, sys, re, facebook, logging
from google.appengine.api import users, urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.api.urlfetch import DownloadError
from django.utils import simplejson as json
from datetime import datetime
from uuid import uuid4

# Stuff for Google calendar
sys.path.insert(0, 'gdata.zip/gdata')
try:
  from xml.etree import ElementTree # for Python 2.5 users
except ImportError:
  from elementtree import ElementTree
import gdata.calendar.service
from gdata.service import NonAuthSubToken, RequestError
import gdata.service
import atom.service
import gdata.calendar
import atom
import getopt
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
  bday_cal = db.LinkProperty()
  event_cal = db.LinkProperty()
  events = db.TextProperty()
  birthdays = db.TextProperty()

class Feed(db.Model):
  user_id = db.StringProperty(required=True)
  feed_id = db.StringProperty(required=True)
  auth_token = db.StringProperty(required=True)
  feed_type = db.StringProperty(required=True, choices=set(["birthdays", "events"]))

def valid_birthday(day, month):
  """Take a day + month and make sure it's a valid date."""
#  day = day + 1

  try:
    birthday = datetime(datetime.today().year, month, day)
  except ValueError:
    return False
  except TypeError:
    return False
  else:
    return birthday.strftime('%B %d')

def parse_birthday(facebook_string):
  """Parse a Facebook birthday, return it in a Gcal friendly string or None"""
  date_regexp = re.compile("^([0-9]+)/([0-9]+)/?([0-9]*)$")
  birthday = date_regexp.search(facebook_string)
  if birthday:
    return valid_birthday(int(birthday.groups()[1]), int(birthday.groups()[0]))

def grab_birthdays(user):
  """Take a user and return a list of their birthdays"""
  graph = facebook.GraphAPI(user.facebook_token)
  
  friends = graph.get_object("me/friends", fields="link,birthday,name,picture")

  # I really do not like this block of code :(
  results = []
  for friend in friends['data']:    
    birthday = parse_birthday(friend.get('birthday', ''))
    if birthday:
      results.append({'id': friend['id'],
                      'name': friend['name'], 
                     'pic': friend['picture'], 
                     'bday': birthday})
  return results

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

def gcal_connect(facebook_id, email, facebook_token, token_param):
  """Firstly check the database for this user, see if they have a working
  token.
  
  If not check the token parameter, upgrade that to a nice session token
  and store it in the database.

  Return the user and calendar object or None if there are no working tokens."""
  # First check the database
  user = Users.all().filter("facebook_id =", facebook_id)
  if user.count():
    # Already registered, make sure token is valid
    calendar_service = check_google_token(user[0].google_token)
    
    if calendar_service:
      # Great we're done
      return user[0], calendar_service
    
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

      # Create their Calendars 
      updates = [{'type': 'addbdaycal'}, {'type': 'addeventcal'}]
      enqueue_updates(updates, user.google_token, '')
      # Great a new user's first time
      return user, calendar_service
  # Saves us a job later
  return None, None

def create_calendar(gcal, title, summary):
  """Simple wrapper to create a new Goolge Calendar."""
  calendar = gdata.calendar.CalendarListEntry()
  calendar.title = atom.Title(text=title)
  calendar.summary = atom.Summary(text=summary)
  calendar.where = gdata.calendar.Where(value_string='Facebook')
  calendar.timezone = gdata.calendar.Timezone(value='UTC')
  calendar.hidden = gdata.calendar.Hidden(value='false')
  calendar.color = gdata.calendar.Color(value='#2952A3')
  return gcal.InsertCalendar(new_calendar=calendar)

def find_calendar(gcal, calendar_link):
  """Return a calendar or None if not found"""
  try:
    return gcal.Query(calendar_link)
  except RequestError:
    return None

def update_events(user, calendar):
  return None

def list_contains(needle, haystack):
  """Does a list contain something? Return something if yes or None if no"""
  try:
    haystack.index(needle)
  except ValueError:
    return None
  else:
    return needle

def any_changes(new, old):
  """Take two dict's and look for differences in equivalent key's values.
  (Does not look for missing or extra entries.) Returns True or False"""
  for k,v in new.iteritems():    
    if v != old[k]:
      return True
  return False

def diff_birthdays(new_bdays, old_birthdays):
  """Take a list of new and old birthdays and return a list of changes to make.
Examples of the change format:
{'id': '342432423', 'type': 'update', changes: {'title': 'newtitle'}}
{'id': '342432423', 'type': 'insert', 'title': 'newtitle', ... }
{'id': '342432423', 'type': 'delete'}"""
  # There has got to be a better way
  updates = []

  # Check for deletes
  new_bday_ids = [b['id'] for b in new_bdays]
  for birthday in old_birthdays:
    if not list_contains(birthday['id'], new_bday_ids):
      # Delete entry
      updates.append({'type': 'delete', 'id': birthday['id']})

  # Kludge the old bdays into a dict so we can look up by the id more easily  
  old_bdays = {}
  for birthday in old_birthdays:
    old_bdays[birthday['id']] = birthday

  # Check for inserts and updates
  for birthday in new_bdays:
    if not old_bdays.has_key(birthday['id']):
      # New entry
      birthday['type'] = 'insert'
      updates.append(birthday)
    else:
      # Check for any differences
      if any_changes(birthday, old_bdays[birthday['id']]):
        birthday['type'] = 'update'
        updates.append(birthday)
          
  return updates

def enqueue_updates(updates, token, calendar, chunk_size=20):
  """Take a list of updates and add them to the Task Queue."""
  for i in range(0, len(updates), chunk_size):
    taskqueue.add(url='/worker',
                  params={'tasks': json.dumps(updates[i:i+chunk_size]),
                          'calendar': calendar,
                          'token': token})

def gcal_quick_add(gcal, calendar, content, fb_id,
                   event=gdata.calendar.CalendarEventEntry()):
  """Wrapper for the quick add Google Calendar feature."""
  event.content = atom.Content(text=content)
  event.quick_add = gdata.calendar.QuickAdd(value='true')
  fb_id_property = gdata.calendar.ExtendedProperty(name="fb_id", value=fb_id)
  event.extended_property.append(fb_id_property)
  logging.info("Creating Event: " + content)
  return gcal.InsertEvent(event, calendar)

def format_extended_dict(d):
  """Take a dictionary and format it for use with a ExtendedProperty query."""
  output = ''
  for k,v in d.iteritems():
    output += '[' + str(k) + ':' + str(v) + ']'
  return output

def find_event(gcal, calendar, search_term=None, extended=None):
  """Searches the given calendar for the search text. Returns the first result
  or None."""
  # Set up the search query
  if extended:
    params = {'extq': format_extended_dict(extended)}
  else:
    params = None

  print(str(extended))

  query = gdata.calendar.service.CalendarEventQuery('default', 
                                                    'private', 
                                                    'full',
                                                    params=params)
  query.__dict__['feed'] = calendar
  if search_term:
    query.text_query = search_term

  # Return the results
  try:
    return calendar_service.CalendarQuery(query)[0]
  except:
    logging.info('Coudln\'t find event ' + (search_term or str(params)))
    return None

class worker(webapp.RequestHandler):
  """Handles /worker requests which processes the work from task queue"""
  def post(self):
    # Grab the parameters
    tasks = json.loads(self.request.get("tasks"))
    calendar = self.request.get("calendar")
    token = self.request.get("token")

    # Connect to Google calendar
    gcal = check_google_token(token)
    
    # Do the workSetup all the tasks
    for task in tasks:
      if task['type'] == 'addbdaycal':
        # Adding a new calendar
        logging.info("Adding calendar Birthdays")
        bday_cal = create_calendar(gcal,
                                    'Birthdays',
                                    'Facebook friend birthdays')
        print " searching ... " +token

        user = Users.all().filter("google_token =", token)[0]
        user.bday_cal = bday_cal.GetEditLink().href
        user.put()
      if task['type'] == 'addeventcal':
        # Adding a new calendar
        logging.info("Adding calendar Events")
        event_cal = create_calendar(gcal,
                                    'Events',
                                    'Facebook events')
        user = Users.all().filter("google_token =", token)[0]
        user.event_cal = event_cal.GetEditLink().href
        user.put()
      if task['type'] == 'insert':
        # Adding a new event
        logging.info("Adding event " + str(event.title))
        content = task['name'] + "'s Birthday " + task['bday'] + " yearly"
        event = gcal_quick_add(gcal, calendar, content, task['id'])
      if task['type'] == 'update':
        # Updating an event with changes
        event = find_event(gcal, calendar, extended={'fb_id':task['id']})
        if event:
          logging.info("Updating event " + str(event.title))
          content = task['name'] + "'s Birthday " + task['bday'] + " yearly"
          event = gcal_quick_add(gcal, calendar, content, task['id'], event)
          gcal.UpdateEvent(event.GetEditLink().href, event)
      if task['type'] == 'remove':
        # Old event we need to delete
        event = find_event(gcal, calendar, extended={'fb_id':task['id']})
        if event:
          logging.info("Deleting event " + str(event.title))
          calendar_service.DeleteEvent(event.GetEditLink().href)  

def update_birthdays(user, gcal, bday_cal):
  """Figure out what needs updating for the birthdays calendar. If there are any
changes to do, queue them up and return a count. If not return None."""
  # TODO
  #X1 - Grab the birthdays from Facebook
  #X2 - Store that as a big TEXT field in the Datastore?
  #X3 - If there was an existing entry in the Datastore diff the two entrys
  #X    before overwriting. We can see if there have been any changes.
  # 4 - Add the changes to the Task Queue*
  # 5 - Setup the Task Queue handler to go and update Google Calendar
  # 6 - Test all that and then delete the ical stuff
  #
  # * http://code.google.com/appengine/docs/python/taskqueue/

  # Grab all the birthdays and figure out what's new
  birthdays = grab_birthdays(user)
  try:
    past_birthdays = json.loads(user.birthdays)
  except:
    past_birthdays = []
  changed_birthdays = diff_birthdays(birthdays, past_birthdays)
  
  if changed_birthdays:
    # Update our database
    user.birthdays = json.dumps(birthdays)
    user.put()
    # Add the changes to the Task Queue
    enqueue_updates(changed_birthdays, 
                    gcal.GetAuthSubToken(), 
                    bday_cal.content.src)
    return len(changed_birthdays)
  else: 
    return None
    
#  event = gdata.calendar.CalendarEventEntry()
#  event.content = atom.Content(text='Tennis with John October 30 3pm-3:30pm')
#  event.quick_add = gdata.calendar.QuickAdd(value='true')
#  return gcal.InsertEvent(event, bday_cal.content.src)
  
def maintain_calendars(gcal, user):
  """With the google calendar connection update the user's calendars.
  Check the calendars exist, update existing calendars. If neither exist
  revoke the google token and delete the user from our database.
  Returns True if connected or False if not."""
  bday_cal = find_calendar(gcal, user.bday_cal)
  if bday_cal:
    bday_changes = update_birthdays(user, gcal, bday_cal)
  
  event_cal = find_calendar(gcal, user.event_cal)
  if event_cal:
    event_changes = update_events(user, gcal)

  if event_cal or bday_cal:
    return True, bday_changes, event_changes
  else:
    # gcal.AuthSubRevokeToken()
    user.delete()
    return False

class gcal(webapp.RequestHandler):
  def get(self):
    # Set my userid for now
    facebook_id = '691580472'
    email = 'kzar@kzar.co.uk'
    facebook_token = 'xXxXxXxXxXx|fa9647df24f2f166ad5251e4-691580472|lugPxybzOCHh7aPKLPTycml5T9Y'

    user, gcal = gcal_connect(facebook_id, email, 
                        facebook_token, self.request.get("token"))
  
    if gcal:
      if user.bday_cal or user.event_cal:
        connected, bday_updates, event_updates = maintain_calendars(gcal, user)
      else:
        bday_updates = 'blah'
        connected = True
      self.response.out.write('<p>Connected to Google calendars.. </p>')
      self.response.out.write('<b>' + str(bday_updates) + ' changes added to queue</b>')
    
    if not gcal or not connected:
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
          logging.info("Rendering birthdays feed.")
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
