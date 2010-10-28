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

def valid_birthday(day, month):
  """Take a day + month and make sure it's a valid date."""
  try:
    birthday = datetime(datetime.today().year, month, day)
  except ValueError:
    return False
  except TypeError:
    return False
  else:
    return birthday.day, birthday.month

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
    try:
      day, month = parse_birthday(friend.get('birthday', ''))
      results.append({'id': friend['id'],
                      'name': friend['name'], 
                      'pic': friend['picture'], 
                      'day': day,
                      'month': month})
    except TypeError:
      pass
  return results

def GetAuthSubUrl(url):
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

      # Setup the new user's calendars
      enqueue_tasks([{'type': 'new-user'}], user.google_token)
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

def birthday_event_task(birthday, task_type, calendar):
  """Helpful function to take a birthday and return a task ready to be
  put in the task queue."""
  # Get everything ready
  title = birthday['name'] + "'s Birthday"
  year = datetime.today().year
  start = datetime(year, birthday['month'], birthday['day'], 12, 0)
  start = start.strftime('%Y%m%d')
  end = datetime(year, birthday['month'], birthday['day'], 12, 0)
  end = end.strftime('%Y%m%d')

  # Return the task
  return {'type': task_type, 'title': title, 'content': title,
          'start': start, 'end': end, 'picture': birthday['pic'],
          'fb_id': birthday['id'], 'calendar': calendar, 'repeat': 'YEARLY'}

def diff_birthdays(new_bdays, old_birthdays, calendar):
  """Take a list of new and old birthdays and return a list of changes to make.
"""
  # Create the updates list, this will contain tasks for any birthday
  # changes that need to be carried out. 
  updates = []

  # Check for deleted birthdays
  new_bday_ids = [b['id'] for b in new_bdays]
  for birthday in old_birthdays:
    if not list_contains(birthday['id'], new_bday_ids):
      # Delete entry
      updates.append(birthday_event_task(birthday, 'remove-event', calendar))
  # Kludge the old bdays into a dict so we can look up by the id more easily  
  old_bdays = {}
  for birthday in old_birthdays:
    old_bdays[birthday['id']] = birthday

  # Check for inserts and updates
  for birthday in new_bdays:
    if not old_bdays.has_key(birthday['id']):
      # New entry
      updates.append(birthday_event_task(birthday, 'insert-event', calendar))
    else:
      # Check for any differences
      if any_changes(birthday, old_bdays[birthday['id']]):
        updates.append(birthday_event_task(birthday, 'update-event', calendar))
    
  return updates

def enqueue_tasks(updates, token, chunk_size=10):
  """Take a list of updates and add them to the Task Queue."""
  for i in range(0, len(updates), chunk_size):
    taskqueue.add(url='/worker',
                  params={'tasks': json.dumps(updates[i:i+chunk_size]),
                          'token': token})

def create_event(title, content, start, end, 
                 repeat_freq=None, fb_id=None, pic=None):
  """Create a new event based on the given parameters and return it."""
  event = gdata.calendar.CalendarEventEntry()
  event = populate_event(event, title, content, start, end, 
                         repeat_freq=repeat_freq, fb_id=fb_id, pic=pic)
  return event

def populate_event(event, title, content, start, end, 
                   repeat_freq=None, fb_id=None, pic=None):
  """Take an event, populate it with all the information and then return it."""
  # For repeat it's start.strftime('%Y%m%d')
  # for single it's start.strftime('%Y-%m-%dT%H:%M:%S.000Z')

  if repeat_freq:
    # This is a repeating event, setup the rule
    recurrence_data = ("DTSTART;VALUE=DATE:" + start + "\r\n" + 
                       "DTEND;VALUE=DATE:" + end + "\r\n" + 
                       "RRULE:FREQ=" + repeat_freq + "\r\n")
    event.recurrence = gdata.calendar.Recurrence(text=recurrence_data)
  else:
    # One off event, set the start / end times
    event.when.append(gdata.calendar.When(start_time=start, end_time=end))
  
  if fb_id:
    # Add the facebook id to the extended properties
    # (This overwrites any other ones, re-write this if that matters.)
    fb_id_property = gdata.calendar.ExtendedProperty(name="+fb_id+", 
                                                     value=fb_id)
    event.extended_property = [fb_id_property]

  if pic:
    # Add the picture
    # (Assumes it's a JPEG and overwrites others.)
    web_content_link = gdata.calendar.WebContentLink(title=title, 
                                                     href=pic, 
                                                     link_type="image/jpeg")
    event.link = [web_content_link]

  # Finish up and return
  event.title = atom.Title(text=content)
  event.content = atom.Content(text=content)
  return event

def format_extended_dict(d):
  """Take a dictionary and format it for use with a ExtendedProperty query."""
  output = ''
  for k,v in d.iteritems():
    output += '[' + str(k) + ':' + str(v) + ']'
  return output

def find_event(gcal, calendar, search_term=None, extended=None):
  """Searches the given calendar for the search text. 
  Returns the results and a list of any further tasks that need to be done."""
  # Set up the search query
  if extended:
    params = {'extq': format_extended_dict(extended)}
  else:
    params = None

  query = gdata.calendar.service.CalendarEventQuery('default', 
                                                    'private', 
                                                    'full',
                                                    params=params)
  query.__dict__['feed'] = calendar
  if search_term:
    query.text_query = search_term

  # Run the search
  try: 
    results = gcal.CalendarQuery(query).entry
  except (DownloadError, RequestError), e:
    # Error running the search, retry
    logging.error('Received error when searching, retrying.')
    return [], True
  except IndexError:
    # No matches
    logging.info('Coudln\'t find event ' + (search_term or str(params)))
    return [], False
  else:
    return results, False

def handle_newuser_event(task, gcal, token):
  """We have a new user, file some paperwork and return a few further tasks
  to get them all set up and ready."""
  logging.info("Setting up new user.")
  return [{'type': 'insert-calendar', 'name': 'Birthdays', 
           'desc': 'Facebook friend birthdays', 'datastore': 'bday_cal'},
          {'type': 'insert-calendar', 'name': 'Events',
           'desc': 'Facebook events', 'datastore': 'event_cal'},
          {'type': 'update-birthdays'}]

def handle_updatebirthdays(task, gcal, token):
  """This event updates the users birthdays. It returns a list of tasks needed
  to be completed to bring the user's birthday calendar up to date."""
  # Find the user in the database
  user = Users.all().filter("google_token =", token)[0]

  # Grab all the birthdays and figure out what's new
  birthdays = grab_birthdays(user)
  try:
    past_birthdays = json.loads(user.birthdays)
  except:
    past_birthdays = []

  # Grab a list of tasks for all the changes we need to make
  changes = diff_birthdays(birthdays, past_birthdays, user.bday_cal)

  if changes:
    logging.info('We found ' + str(len(changes)) + ' to make. Adding tasks')
    # Update our database
    user.birthdays = json.dumps(birthdays)
    user.put()
  else:
    logging.info('No changes to make.')

  return changes  

def handle_insert_event(task, gcal, token):
  """Take an insert event task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  logging.info("Adding event " + task['title'])
  try:
    event = create_event(task['title'], task['content'], task['start'],
                         task['end'], task['repeat'], task['fb_id'], 
                         task['picture'])
    gcal.InsertEvent(event, task['calendar'])
  except (DownloadError, RequestError), err:
    logging.info("Couldn't add event, " + task['title'] + "retrying.")
    logging.debug("Download error: " + str(err))
    return [task]
  else:
    return []
  
def handle_update_event(task, gcal, token):
  """Take an update event task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  # Find the event
  events, search_failed = find_event(gcal, task['calendar'], 
                                     extended={'+fb_id+':task['fb_id']})
  
  # Search for event failed, we should retry
  if search_failed:
    return [task]

  if events:
    for event in events:
      logging.info("Updating event " + str(event.title.text))
      edit_link = event.GetEditLink().href
      event = populate_event(event, task['title'], task['content'], 
                             task['start'], task['end'], task['repeat'],
                             task['fb_id'], task['picture'])
      try:
        gcal.UpdateEvent(edit_link, event)
      except (DownloadError, RequestError):
        logging.error("Couldn't update event, " + task['title'] + "retrying.")
        return [task]
  else:
    logging.error("Couldn't find event to update:" + task['fb_id'])
  return []


def handle_remove_event(task, gcal, token):
  """Take a update event task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  # Find the event to remove
  events, search_failed = find_event(gcal, task['calendar'], 
                                     extended={'+fb_id+':task['id']})

  # Search for event failed, we should retry
  if search_failed:
    return [task]

  if events:
    for event in events:
      logging.info("Deleting event " + str(event.title))
      try:
        calendar_service.DeleteEvent(event.GetEditLink().href)  
      except DownloadError:
        logging.error("Couldn't delete event, " + task['title'] + "retrying.")
        return [task]
  else:
    logging.error("Couldn't find event to delete:" + task['id'])
  return []

def handle_insert_calendar(task, gcal, token):
  """Take an insert calendar task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  # Create the calendar
  logging.info("Adding calendar " + task['name'])

  try:
    new_cal = create_calendar(gcal, task['name'], task['desc'])
  except (RequestError, DownloadError):
    logging.error("Couldn't add calendar " + task['name'] + " going to retry.")
    return [task]
  else:
    # Record the calendar in the user's datastore
    datastore = task.get('datastore', None)
    if datastore:
      user = Users.all().filter("google_token =", token)[0]      
      setattr(user, datastore, new_cal.content.src)
      user.put()
    # Done
    return []
  
def handle_update_calendar(task, gcal, token):
  """Take an update calendar task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  pass

def handle_remove_calendar(task, gcal, token):
  """Take a update calendar task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  pass

def handle_unknown_task(task, gcal, token):
  logging.info('Unkown task type "' + task['type'] + '"')
  return []

class worker(webapp.RequestHandler):
  """Handles /worker requests which processes the work from task queue"""
  def post(self):
    # Grab the parameters
    tasks = json.loads(self.request.get("tasks"))
    token = self.request.get("token")

    # Connect to Google calendar
    gcal = check_google_token(token)
    
    # Future tasks is a list of new tasks to enqueue, 
    # generated while we have been dealing with the current tasks
    future_tasks = []

    # Map task types to handler functions
    handlers = {'insert-calendar': 'handle_insert_calendar',
                'update-calendar': 'handle_update_calendar',
                'remove-calendar': 'handle_remove_calendar',
                'insert-event': 'handle_insert_event',
                'update-event': 'handle_update_event',
                'remove-event': 'handle_remove_event',
                'new-user': 'handle_newuser_event',
                'update-birthdays': 'handle_updatebirthdays'}

    # Deal with the tasks
    for task in tasks:
      handler = globals()[handlers.get(task['type'], 'handle_unknown_task')]
      future_tasks.extend(handler(task, gcal, token))

    # FIXME
    # Newly returned tasks should be pushed infront of existing ones
    # in the queue, older ones should really be queued up again to 
    # prevent problems. Also we shouldn't need to specify the calendar.
    
    # Enqueue any future tasks we need to deal with
    enqueue_tasks(future_tasks, token)

class gcal(webapp.RequestHandler):
  def get(self):
    # Set my userid for now
    facebook_id = '691580472'
    email = 'kzar@kzar.co.uk'
    facebook_token = 'xXxXxXxXxXx|fa9647df24f2f166ad5251e4-691580472|lugPxybzOCHh7aPKLPTycml5T9Y'

    user, gcal = gcal_connect(facebook_id, email, 
                        facebook_token, self.request.get("token"))
  
    if gcal:
      if user.bday_cal:
        enqueue_tasks([{'type':'update-birthdays'}], user.google_token)
      if user.event_cal:
        enqueue_tasks([{'type':'update-events'}], user.google_token)      
      self.response.out.write('<p>Connected to Google calendars.. </p>')
    else:
      self.response.out.write('<a href="%s">Login to your Google account</a>' % 
                              GetAuthSubUrl(self.request.url))      

    self.response.out.write('<br /><br /><a href="/search/term/Diyan Gochev\'s Birthday">Search term</a><a href="/search/id/13803817">Search ID</a>')
    
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

class search(webapp.RequestHandler):
  def get(self, *ar):
    search_type = ar[0]
    term = ar[1]

    facebook_id = '691580472'
    email = 'kzar@kzar.co.uk'
    facebook_token = 'xXxXxXxXxXx|fa9647df24f2f166ad5251e4-691580472|lugPxybzOCHh7aPKLPTycml5T9Y'

    user, gcal = gcal_connect(facebook_id, email, 
                        facebook_token, self.request.get("token"))

    calendar = user.bday_cal
    
    if search_type == 'term':
      events, search_failed  = find_event(gcal, calendar, search_term=term)
    elif search_type == 'id':
      events, search_failed  = find_event(gcal, calendar, 
                                          extended={'+fb_id+':term})

    if search_failed:
      self.response.out.write('<b>The search failed, refresh page!</b>')

    if events:
      for event in events:
        self.response.out.write(str(event.title.text) + 
                                " [" + str(event.extended_property[0].name) +
                                ":" + str(event.extended_property[0].value) + "]" +
                                " " + str(len(event.extended_property)) + '\n')
    else:
      self.response.out.write('<b>No matches</b>')
