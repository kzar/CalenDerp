import os, sys, re, facebook, logging
from google.appengine.api import users, urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.api.urlfetch import DownloadError
from django.utils import simplejson as json
from datetime import datetime, timedelta
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

class Flags(db.Model):
  flag_key = db.StringProperty(required=True)
  value = db.StringProperty(required=True)

def handle_google_error(err):
  """Take a Google error and return a lists of tasks to carry out based on
  it. Just a shell for now but could be useful in the future."""
  logging.info("Google error: " + str(err))
  if 'quota' in str(err):
    delay_tasks()
  return []

def set_flag(key, value):
  """Set a flag in the datastore's value."""
  flag = Flags.all().filter("flag_key =", key).get()
  if flag:
    # Flag already exists, update it
    flag.value = value
  else:
    # Flag doesn't exist, create it
    flag = Flags(flag_key=key, value=value)
  # Great we're done, save it
  flag.put()

def get_flag(key):
  """Get a flag's value from the datastore."""
  flag = Flags.all().filter("flag_key =", key).get()
  if flag:
    return flag.value

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

def parse_date(date):
  """Takes an ISO date string, parses it and returns a datetime object."""
  try:
    return datetime(*map(int, re.split('[^\d]', date)[:-1]))
  except:
    return None

def grab_events(user):
  """Take a user and return a list of their events."""
  # I'm deliberately keeping this simple for now
  # (Does not return past events, only returns
  # events they are attending, is limited to one page of results.)
  graph = facebook.GraphAPI(user.facebook_token)
  
  fields = "name,id,location,start_time,end_time,description"
  events = graph.get_object("me/events/attending", fields=fields)

  today = datetime.today()
  #today = datetime(2009,5,1)
  results = []
  for event in events['data']:
    try: 
      if parse_date(result['end_time']) > today:
        results.append({'name': event['title'],
                        'content': event['description'],
                        'start': event['start_time'],
                        'end': event['end_time'],
                        'id': event['id'],
                        'location': event['location']})
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

def format_birthdaytask(birthday, task_type, calendar):
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

def format_eventtask(event, task_type, calendar):
  """Helpful function to take an event and return a task ready to be
  put in the task queue."""
  return {'type': task_type, 'title': event['name'], 
          'calendar': calendar, 'content': event['content'],
          'start': event['start'], 'end': event['end'], 
          'fb_id': event['id'], 'location': event['location']}

def enqueue_tasks(updates, token, chunk_size=10):
  """Take a list of updates and add them to the Task Queue."""
  # Makes sure the task queue really does wait if we're outa quota
  run_date = parse_date(get_flag('next-task-run-date'))
  if run_date and run_date > datetime.today():
    eta = run_date
  else:
    eta = None

  # Now add those tasks :)
  for i in range(0, len(updates), chunk_size):
    taskqueue.add(url='/worker',
                  params={'tasks': json.dumps(updates[i:i+chunk_size]),
                          'token': token},
                  eta=eta)

def create_event(title, content, start, end, location=None, repeat_freq=None,
                 fb_id=None, pic=None):
  """Create a new event based on the given parameters and return it."""
  event = gdata.calendar.CalendarEventEntry()
  event = populate_event(event, title, content, start, end, location=location,
                         repeat_freq=repeat_freq, fb_id=fb_id, pic=pic)
  return event

def populate_event(event, title, content, start, end, 
                   repeat_freq=None, fb_id=None, pic=None, location=None):
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

  if location:
    # Add the location
    event.where = [gdata.calendar.Where(value_string=location)]

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
  except (DownloadError, RequestError), err:
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
          {'type': 'update-events'},
          {'type': 'update-birthdays'}]

def diff_data(new_data, old_data, calendar, format_task_function):
  """Take a list of new and old data, check for differences and return
  a list of tasks needed to be performed to bring things up to date."""
  # Python requires we set this up in advance
  tasks = []

  # No past data, add it all and return
  if not old_data:
    for entry in new_data:
      tasks.append(format_task_function(entry, 'insert-event', calendar))
    return tasks

  # No existing data, query probably failed, skip
  if not new_data:
    return []

  # Check for deleted data
  new_data_ids = [b['id'] for b in new_data]
  for old_entry in old_data:
    if not list_contains(old_entry['id'], new_data_ids):
      # Delete entry
      tasks.append(format_task_function(old_entry, 'remove-event', calendar))

  # Make a dict out of the old data so we can look records up quickly
  old_data_dict = {}
  for entry in old_data:
    old_data_dict[entry['id']] = entry

  # Check for inserts and tasks
  for new_entry in new_entry:
    if not old_data_dict.has_key(new_entry['id']):
      # New entry
      tasks.append(format_task_function(new_entry, 'insert-event', calendar))
    else:
      # Check for any differences
      if any_changes(new_entry, old_data_dict[new_entry['id']]):
        tasks.append(format_task_function(new_entry, 'update-event', calendar))
    
  return tasks

def update_data(google_token, grab_function, format_function, 
                datastore_key, calendar):
  """Take all the details needed to update a user's data. This is kept generic
  so we can use it to update both birthdays and events. Return a list of tasks
  that need to be carried out to perform the update."""
  # Find the user in the database
  user = Users.all().filter("google_token =", google_token)[0]

  # Grab the data from Facebook
  data = grab_function(user)
  old_data = getattr(user,datastore_key)
  
  logging.info('AHH' + str(data) + 'wahh' + str(old_data))

  # Check for changes
  changes = diff_data(data, old_data, calendar, format_function)
  
  if changes:
    # Record their new data in the datastore
    logging.info('We found ' + str(len(changes)) + ' to make. Adding tasks')
    setattr(user, datastore_key, json.dumps(data))
    user.put()
  # We're done, give them the list of changes
  return changes

def grab_one_user_field(google_token, datastore_key):
  """Quick little helper function, look up a user by their token and return
  the contents of the given key for that user."""
  user = Users.all().filter("google_token =", google_token)[0]
  return getattr(user, datastore_key)

def handle_updateevents(task, gcal, token):
  """This updates the user's events. It grabs the latest events, checks for 
  anything new and returns a list of tasks to make the needed changes."""
  logging.info('Checking for events to update')
  # If the calendar hasn't been given look it up
  calendar = task.get('calendar', grab_one_user_field(token, 'event_cal'))
  # Don't freak out if there's no calendar
  if not calendar:
    logging.info("No event calendar yet, retry later.")
    return [task]
  # Great now return the results
  return update_data(token, grab_events, format_eventtask, 
                     'events', calendar)
  
def handle_updatebirthdays(task, gcal, token):
  """This event updates the users birthdays. It returns a list of tasks needed
  to be completed to bring the user's birthday calendar up to date."""
  logging.info('Checking for birthdays to update')
  # If the calendar hasn't been given look it up
  calendar = task.get('calendar', grab_one_user_field(token, 'bday_cal'))
  
  if not calendar:
    logging.info("No birthday calendar yet, retry later.")
    return [task]

  # FIXME - check the birthday calendar exists! 
  # (not "" and valid and returns 200)

  # Great now return the results
  return update_data(token, grab_birthdays, format_birthdaytask, 
                     'birthdays', calendar)

def handle_insert_event(task, gcal, token):
  """Take an insert event task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  logging.info("Adding event " + task['title'])
  try:
    event = create_event(task['title'], task['content'], task['start'],
                         task['end'], repeat_freq=task['repeat'], 
                         fb_id=task['fb_id'], pic=task['picture'])
    gcal.InsertEvent(event, task['calendar'])
  except (DownloadError, RequestError), err:
    logging.info("Couldn't add event, " + task['title'] + " retrying.")
    return handle_google_error(err) + [task]
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
                             task['start'], task['end'], 
                             repeat_freq=task['repeat'],
                             fb_id=task['fb_id'], pic=task['picture'])
      try:
        gcal.UpdateEvent(edit_link, event)
      except (DownloadError, RequestError), err:
        logging.error("Couldn't update event, " + task['title'] + "retrying.")
        return handle_google_error(err) + [task]
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
        return handle_google_error + [task]
  else:
    logging.error("Couldn't find event to delete:" + task['id'])
  return []

def delay_tasks(message="hoooooooooooooolllllld-up! brap brap"):
  """When we receive a 'quota depleated' error we need to put everything on
  hold. For now we just stall by 1 day, maybe we will make this smarter in
  the future?"""
  logging.info(message)
  tomorrow = datetime.today() + timedelta(days=1)
  set_flag('next-task-run-date', tomorrow.strftime('%Y-%m-%dT%H:%M:%S.000Z'))

def handle_insert_calendar(task, gcal, token):
  """Take an insert calendar task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  # Create the calendar
  logging.info("Adding calendar " + task['name'])

  try:
    new_cal = create_calendar(gcal, task['name'], task['desc'])
  except (RequestError, DownloadError), err:
    return handle_google_error(err) + [task]
    if 'quota' in str(err):
      delay_tasks()
      return [task]
    else:
      # Looks ok, let's just retry
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

    # Check we can run now, if this date is in the future it means our
    # quota is used up or something else has happened requiring us to wait.
    run_date = parse_date(get_flag('next-task-run-date'))
    if run_date and run_date > datetime.today():
      enqueue_tasks(tasks, token)
      return

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
                'update-birthdays': 'handle_updatebirthdays',
                'update-events': 'handle_updateevents'}

    # Deal with the tasks
    for task in tasks:
      handler = globals()[handlers.get(task['type'], 'handle_unknown_task')]
      future_tasks.extend(handler(task, gcal, token))

    # Enqueue any future tasks we need to deal with
    enqueue_tasks(future_tasks, token)

## Cron Job code too refresh ...
#select all users from datastore, loop through with this code:
#    if gcal:
#      if user.bday_cal:
#        enqueue_tasks([{'type':'update-birthdays', 'calendar': user.bday_cal}],
#                      user.google_token)
#      if user.event_cal:
#        enqueue_tasks([{'type':'update-events', 'calendar': user.event_cal}],
#                      user.google_token)      
#Now if both calendars don't exist delete the stuff from datstore
    
class MainPage(webapp.RequestHandler):
  def get(self):
    # Grab the auth_token from facebook's canvas magic
    fb_token = facebook.oauth_token(self.request.get("signed_request"), FACEBOOK_APP_SECRET)

    # Let's see if they're authed        
    if fb_token:
      # Right now let's see if they're authed with Google Calendar
      user, gcal = gcal_connect(facebook_id, email, 
                                facebook_token, self.request.get("token"))
      if gcal:
        # Great they are
        args = {'google_status': 'Connected to Google'}
        page = 'show_status.html'
      else:
        # No dice, display the connect button
        args = {'login_link': GetAuthSubUrl(self.request.url)}
        page = 'google_login.html'
    else:
      # No dice, show them the install button and some convincing copy..
      redirect_uri = "http://apps.facebook.com/calenderp/"
      scope = "offline_access,friends_birthday,user_events"
      args = {'install_link': facebook.oauth_URL(client_id=FACEBOOK_APP_ID, 
                                                 redirect_uri=redirect_uri,
                                                 display="page", scope=scope)}
      page = 'install.html' 
    
    # Either way render the page :)
    path = os.path.join(os.path.dirname(__file__), page);
    self.response.out.write(template.render(path, args))
