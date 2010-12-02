# Copyright Dave Barker 2010.
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os, sys, re, facebook, logging, config, translations, traceback, errors
from google.appengine.api import users, urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.ext import db
from google.appengine.api.urlfetch import DownloadError
from google.appengine.runtime.apiproxy_errors import ApplicationError
from google.appengine.runtime import apiproxy_errors
from django.utils import simplejson as json
from datetime import datetime, timedelta
from uuid import uuid4
from facebook import GraphAPIError
from timezones import PT, UTC

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

def parse_error(message, error, errors_list, error_index_key):
  """Takes an error and a list of errors e.g. the Google errors and returns the
  appropriate action to take. Also logs some details for debugging."""
  # Log some details for debugging
  logging.debug(message)
  logging.debug(str(error))
  logging.debug('Traceback: ' + str(traceback.format_exc()))
  # Create a lookup table from our errors list
  error_lookup = {}
  for e in errors_list:
    error_lookup[e[error_index_key]] = e
  # Lookup the error
  match = error_lookup.get(error[error_index_key], None)  
  # If we know what to do tell them, if not give up
  if match:
    logging.info(match['explanation'])
    return match['action']
  else:
    logging.error('Can\'t handle this error properly, it\'s unknown!')    
    return 'give-up'

def parse_urlfetch_error(err):
  """Take a URLFetch error and parse it."""
  return parse_error("urlfetch Error", {'reason': err.message.strip()},
                     errors.URLFETCH_ERRORS, 'reason')

def parse_facebook_error(err):
  """Take a Facebook error and return an action like 'retry' or 'give-up' based
  on the error's contents."""
  return parse_error("Facebook Error", 
                     {'code': err.type, 'reason': err.message},
                     errors.FACEBOOK_ERRORS, 'code')

def parse_google_error_body(error):
  """Some of Google's errors don't have a proper reason, we have to extract
  it ourselves from the HTML message they give us.."""
  try:
    return re.search("<TITLE>(.+)</TITLE>", error).groups()[0]
  except (AttributeError, KeyError, IndexError):
    pass

def parse_google_error(err):
  """Take a Google error and return an action like 'retry' or 'give-up' based
  on the error."""
  # Either take the error's reason or check the body for one
  reason = err[0].get("reason", parse_google_error_body(err[0]['body']))

  if not reason:
    logging.error("No error reason, giving up. " + str(err[0]))
    return "give-up"

  error = {'code': err[0]['status'], 
           'message': err[0]['body'],
           'reason': reason}

  return parse_error("Google Error", error, errors.GOOGLE_ERRORS, 'reason')

def handle_special_errors(action):
  """Returns tasks for the special error situations like removing tokens.
  Ignores standard stuff like giving up and retrying because they should have
  been dealt with already!"""
  # Get rid of standard stuff
  if action in ['give-up', 'retry']:
    return []
  # Do our job
  if action == 'remove-google-token':
    return [{'type': 'remove-google-token', 'queue': 'fast'}]
  if action == 'remove-facebook-token':
    return [{'type': 'remove-facebook-token', 'queue': 'fast'}]
  # Log anything else for debugging
  else:
    logging.error("Unkown error action: " + str(action) + ", giving up!")
    return []

def handle_error(task, err=None, parser=None, action=None):
  """Helper function to make handling Google + Facebook errors within task 
  handlers easier. Takes an error and the task being processed and returns 
  a list of tasks to perform."""
  # First make sure there really is an error!
  if not err:
    return []
  # Next make sure there are any retrys left for the task
  retrys = task.get('retrys', config.QUERY_RETRYS)
  if (retrys < 1):
    logging.info('We ran out of retrys for this task!')
    return []
  # Now figure out what action should be taken
  # (This might already be set if we've already parsed the error)
  if not action:
    action = parser(err)
  # OK now do it..
  if action == 'retry':
    logging.info(str(retrys) + ' retrys left.')
    task['retrys'] = retrys - 1
    return [task]
  if action == 'give-up':
    return []
  else:
    return handle_special_errors(action)
 
def tackle_error(action, google_token, locale=False):
  """Take a parsed error and the other details and queue up tasks for any
  special occasions like tokens expiring. Otherwise don't do anything. This
  function is useful when we're responding to a user's request and not just
  handling tasks in a queue."""
  # Get a list of tasks we might need to enqueue to handle special errors
  tasks = handle_special_errors(action)
  # For now log someting TODO delete this
  logging.error('Tackling error, tasks: ' + str(tasks))
  # If we have any then enqueue them
  if tasks:
    enqueue_tasks(tasks, google_token, locale)

def tackle_retrys(f, return_error=False, retrys=config.QUERY_RETRYS):
  """Take a function that conforms to the "result, parsed_error" format and 
  keep running it 'till we need to give up or have a result. Used when we need
  to tackle an error head on instead of adding another task to the queue."""
  # Setup return_f function so we can strip error from returns easily
  if return_error:
    return_f = lambda a, b: (a, b)
  else:
    return_f = lambda a, b: a
  # Run out of retrys, fail
  if retrys < 1:
    return return_f(None, True)
  # Grab the results
  result, parsed_error = f()
  # Success, return results
  if parsed_error == False:
    return return_f(result, False)
  # Failure, retry
  elif parsed_error == 'retry':
    return tackle_retrys(f, retrys - 1)
  # Failure, return the error if we can
  else:
    return return_f(None, parsed_error)

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

def we_gotta_wait():
  """Return True if the next-task-run-date is in the future. False otherwise."""
  run_date = parse_date(get_flag('next-task-run-date'))
  if run_date and run_date > datetime.today():
    return run_date
  else:
    return False

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
  
  try:
    friends = graph.get_object("me/friends", 
                               fields="link,birthday,name,picture")
  except GraphAPIError, err:
    return [], parse_facebook_error(err)
  except urlfetch.Error, err:
    return [], parse_urlfetch_error(err)

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
  return results, False

def parse_date(date, tz=None):
  """Takes an ISO date string, parses it and returns a datetime object."""
  try:
    values = map(int, re.split('[^\d]', date))[:-1]
    assert(len(values) > 2)
    return datetime(tzinfo=tz, *values)
  except:
    return None

def grab_events(user):
  """Take a user and return a list of their events."""
  # I'm deliberately keeping this simple for now
  # (Does not return past events, only returns events they are or attendind 
  #  or maybe attending, is limited to one page of results.)
  graph = facebook.GraphAPI(user.facebook_token)
  
  ## Todo
  # The event description is too long really, it would be better to query for
  # this when adding the event rather than storing it and passing it through
  # the event queue.

  fields = "name,id,location,start_time,end_time,description"
  try:
    attending = graph.get_object("me/events/attending", fields=fields)
    maybe = graph.get_object("me/events/maybe", fields=fields)
  except GraphAPIError, err:
    return [], parse_facebook_error(err)
  except urlfetch.Error, err:
    return [], parse_urlfetch_error(err)

  events = attending['data'] + maybe['data']

  today = datetime.now(UTC())
  results = []

  for event in events:
    try: 
      if parse_date(event['end_time'], PT()) > today:
        results.append({'name': event['name'],
                        'content': event.get('description', ''),
                        'start': event['start_time'],
                        'end': event['end_time'],
                        'id': event['id'],
                        'location': event.get('location', '')})
    except TypeError:
      pass
  return results, False

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
    return None, False
  except apiproxy_errors.OverQuotaError:
    delay_tasks()
    return None, 'retry'
  except RequestError, err:
    return None, parse_google_error(err)
  except (DownloadError, urlfetch.Error), err:
    return None, parse_urlfetch_error(err)
  else:
    return calendar_service, False

def upgrade_google_token(token):
  """Take a token string that google gave us and upgrade it
  to a useable session one. Return the calendar object or None"""
  calendar_service = gdata.calendar.service.CalendarService()
  calendar_service.SetAuthSubToken(token)
  calendar_service.UpgradeToSessionToken()
  return (calendar_service)

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

def format_birthdaytask(birthday, task_type, calendar, l):
  """Helpful function to take a birthday and return a task ready to be
  put in the task queue."""
  # Get everything ready
  title = l("%s's Birthday") % birthday['name']
  year = datetime.today().year
  start = datetime(year, birthday['month'], birthday['day'], 12, 0)
  start = start.strftime('%Y%m%d')
  end = datetime(year, birthday['month'], birthday['day'], 12, 0)
  end = end.strftime('%Y%m%d')
  # Return the task
  return {'type': task_type, 'title': title, 'content': title,
          'start': start, 'end': end, 'picture': birthday['pic'],
          'fb_id': birthday['id'], 'calendar': calendar, 'repeat': 'YEARLY',
          'queue': 'slow'}

def format_eventtask(event, task_type, calendar, l, time_difference):
  """Helpful function to take an event and return a task ready to be
  put in the task queue."""
  # Adjust the mangled dates Facebook gives us
  start = parse_date(event['start'], PT()).astimezone(UTC())
  end = parse_date(event['end'], PT()).astimezone(UTC())
  # Put them into the format Google wants
  td = make_timedelta(time_difference)
  start = (start - td).strftime('%Y-%m-%dT%H:%M:%S.000Z')
  end = (end - td).strftime('%Y-%m-%dT%H:%M:%S.000Z')
  # Now return the task
  return {'type': task_type, 'title': event['name'], 'calendar': calendar, 
          'content': event['content'], 'start': start, 'end': end, 
          'fb_id': event['id'], 'location': event['location'], 'queue': 'slow'}

def facebook_user_query(field, datastore_key, user=None, google_token=None,
                        facebook_token=None, default=None, force_update=False,
                        format_f=lambda x : x):
  """This does the work for functions like check_locale and check_timezone.
  It's a common pattern to query Facebook for 1 piece of info if it's not 
  already in the database, update it if different and then return the result."""
  # First find the user
  if not user:
    if google_token:
      user = Users.all().filter("google_token = ", google_token).get()
    elif facebook_token:
      user = Users.all().filter("facebook_token = ", facebook_token).get()
  # Next check the existing data
  if user and not force_update:
    existing = getattr(user, datastore_key)
    # Todo - more useful check for existing being OK
    if existing != None:
      return format_f(existing), False
  # No good, ask Facebook
  graph = facebook.GraphAPI(facebook_token or user.facebook_token)
  try:
    results = graph.get_object("me", fields=field)
  except GraphAPIError, err:
    return None, parse_facebook_error(err)
  except urlfetch.Error, err:
    return None, parse_urlfetch_error(err)
  # Update user if needed
  result = format_f(results.get(field, default))
  if user and result != getattr(user, datastore_key):
    logging.info(datastore_key + ' updated.')
    setattr(user, datastore_key, result)
    user.put()
  return result, False
  
def check_locale(user=None, google_token=None, facebook_token=None):
  """Take a google token, look up the user and return the locale. If we don't
  know their locale yet then ask Facebook and record it."""
  return facebook_user_query('locale', 'locale', user, google_token, 
                             facebook_token)

def is_number_p(x):
  return type(x).__name__ in ['int', 'float', 'complex']

def make_timedelta(hours):
  """Convenience function that gives you a timedelta."""
  if is_number_p(hours):
    return timedelta(hours=hours)
  else:
    return timedelta(0)

def make_float(i):
  if i and is_number_p(i):
    return float(i)

def check_timedifference(user=None, google_token=None, facebook_token=None):
  """Lookup the user's time difference and return it."""
  return facebook_user_query('timezone', 'time_difference', user, google_token,
                             facebook_token, default=0, format_f=make_float)

def update_timedifference(user=None, google_token=None, facebook_token=None):
  """Update the user's time difference and return it."""
  return facebook_user_query('timezone', 'time_difference', user, google_token,
                             facebook_token, default=0, force_update=True, 
                             format_f=make_float)

def grab_eta():
  """Checks the run_date flag, if it's in the future we need to set make sure
  the eta uses it. If it's in the future return the parsed date for the
  task queue, if not None."""
  # Makes sure the task queue really does wait if we're outa quota
  run_date = parse_date(get_flag('next-task-run-date'))
  if run_date and run_date > datetime.today():
    return run_date

def enqueue_tasks(tasks, token, locale):
  """Take a list of tasks and add them to the Task Queue."""
  # Make sure we've got their locale
  if not locale:
    locale = tackle_retrys(lambda: check_locale(google_token=token))
  # Check the eta for the tasks
  eta = grab_eta()
  # Now add those tasks :)
  for task in tasks:
    enqueue_task(token, locale, eta=eta, task=task)

def enqueue_task(token, locale, eta=None, task=None, store=None, 
                 queue="default"):
  """Take a task and add it to the Task Queue, I've seperated this to allow
  for recursive retries on failures."""
  # First save the data for the task in the datastore, this is because tasks
  # can only be so large and I was hitting the limit occasionally.
  if not store:
    store = TaskData(data=json.dumps(task))
    store.put()
  # Figure out the eta for the task
  if not eta:
    eta = grab_eta()
  # Figure out the key for the store
  if type(store).__name__ == 'str':
    store_key = store
  else:
    store_key = str(store.key())
  # Next figure out the correct queue
  if task:
    queue = task.get("queue", queue)
  # Now enqueue the task, give the store's key so we can access all the
  # data when handling it
  try:
    taskqueue.add(url='/worker',
                  queue_name=task.get("queue", "default"),
                  params={"store_key" : store_key,
                          "token" : token,
                          "locale" : locale},
                  eta=eta)
  # Finally catch TransientError (temporary failure to enqueue task) and 
  # handle by giving it another shot recursively. 
  except taskqueue.TransientError:
    enqueue_task(token, locale, eta=eta, task=task, store=store, queue=queue)

def delay_task(store_key, token, locale, queue):
  """This let's task handlers re-queue up a task for later. Used when we've
  hit quota limits."""
  enqueue_task(token, locale, store=store_key, queue=queue)

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
    event.when = [gdata.calendar.When(start_time=start, end_time=end)]
  
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
  event.title = atom.Title(text=title)
  event.content = atom.Content(text=content)
  return event

def format_extended_dict(d):
  """Take a dictionary and format it for use with a ExtendedProperty query."""
  output = ''
  for k,v in d.iteritems():
    output += '[' + str(k) + ':' + str(v) + ']'
  return output

def find_event(gcal, calendar, task, search_term=None, extended=None):
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
  except RequestError, err:
    return [], handle_error(task, err, parse_google_error)
  except (DownloadError, urlfetch.Error), err:
    return [], handle_error(task, err, parse_urlfetch_error)
  except IndexError:
    # No matches
    logging.info('Coudln\'t find event ' + (search_term or str(params)))
    return [], False
  else:
    return results, False

def handle_newuser_event(task, gcal, token, l):
  """We have a new user, file some paperwork and return a few further tasks
  to get them all set up and ready."""
  logging.info("Setting up new user.")
  return [dict({'type': 'insert-calendar', 'queue': 'slow'},
               **config.BIRTHDAY_CALENDAR),
          dict({'type': 'insert-calendar', 'queue': 'slow'},
               **config.EVENT_CALENDAR),
          {'type': 'update-user', 'queue': 'fast'}]

def event_not_in_past(entry):
  return parse_date(entry['end'], PT()) > datetime.now(UTC())

def diff_data(new_data, old_data, calendar, format_task_function, l, 
              delete_check=lambda entry: True):
  """Take a list of new and old data, check for differences and return
  a list of tasks needed to be performed to bring things up to date."""
  # Python requires we set this up in advance
  tasks = []

  # No past data, add it all and return
  if not old_data:
    for entry in new_data:
      tasks.append(format_task_function(entry, 'insert-event', calendar, l))
    return tasks

  # No existing data, query probably failed, skip
  if not new_data:
    return []

  # Check for deleted data
  new_data_ids = [b['id'] for b in new_data]
  for old_entry in old_data:
    if not list_contains(old_entry['id'], new_data_ids):
      # Check it matches our checking function
      if delete_check(old_entry):
        # Delete entry
        tasks.append(format_task_function(old_entry, 
                                          'remove-event', calendar, l))

  # Make a dict out of the old data so we can look records up quickly
  old_data_dict = {}
  for entry in old_data:
    old_data_dict[entry['id']] = entry

  # Check for inserts and tasks
  for new_entry in new_data:
    if not old_data_dict.has_key(new_entry['id']):
      # New entry
      tasks.append(format_task_function(new_entry, 'insert-event', calendar, l))
    else:
      # Check for any differences
      if any_changes(new_entry, old_data_dict[new_entry['id']]):
        tasks.append(format_task_function(new_entry, 'update-event', calendar,
                                          l))
    
  return tasks

def update_data(task, google_token, grab_function, format_function, 
                datastore_key, calendar, l, delete_check=lambda entry: True):
  """Take all the details needed to update a user's data. This is kept generic
  so we can use it to update both birthdays and events. Return a list of tasks
  that need to be carried out to perform the update."""
  # Find the user in the database
  user = Users.all().filter("google_token =", google_token).get()

  # Make sure there's a Facebook token!
  if not user.facebook_token:
    return handle_error(task, action='give-up')

  # Grab the data from Facebook
  data, parsed_error  = grab_function(user)
  if parsed_error != False:
    return handle_error(task, action=parsed_error)
    
  old_data = getattr(user,datastore_key)
  if old_data:
    old_data = json.loads(old_data)    

  # Check for changes
  changes = diff_data(data, old_data, calendar, format_function, l, 
                      delete_check)

  if changes:
    # Record their new data in the datastore
    logging.info('We found ' + str(len(changes)) + ' to make. Adding tasks')
    setattr(user, datastore_key, json.dumps(data))
    user.put()
  # We're done, give them the list of changes
  return changes

def list_calendars(gcal):
  calendars = []
  feed = gcal.GetOwnCalendarsFeed()
  for i, calendar in enumerate(feed.entry):
    link = calendar.GetAlternateLink() and calendar.GetAlternateLink().href
    if link:
      title = (calendar.title and calendar.title.text) or " "
      description = str(calendar.summary and calendar.summary.text)
      calendars.append({'title': title,
                        'description': description,
                        'link': link})
  return calendars

def find_calendar(calendars, l, link=None, description=None, link_key=None,
                  data_key=None, **junk_args):
  """Take a list of calendars and the details of the calendars we are interested
  in. Search the list for the calendar, return the calendar's link if we can
  find it or None otherwise. The second return value is a boolean, True if
  the calendar link given was out of date."""
  # First check for the link, the best way to find a calendar by far
  if link:
    for calendar in calendars:
      if calendar['link'] == link:
        return link, False
  # Oh dear, well let's check for a matching description.. scraping the barrel
  if description:
    for calendar in calendars:
      if calendar['description'].decode("utf-8") == l(description):
        return calendar['link'], True
  # We could search by Title but I think that's a bad idea, too vague
  if link:
    return None, True
  else:
    return None, False

def ascii_keys(dictionary):
  """Python doesn't let you have unicode keys in a dictionary in certain
  situations. You get a 'keywords must be strings' error so this function
  takes a dict and returns one that Python can use.. grr"""
  ascii_dict = {}
  for k,v in dictionary.items():
    ascii_dict[k.encode("ascii")] = v
  return ascii_dict

def lookup_calendar(calendar_link, details, gcal, token, l):
  """Take a calendar link, the details about a calendar (in config.py),
  a google calendar connection + token. Use the link given if it exists,
  otherwise take the link from the datastore. Now make sure the calendar still
  exists and is up to date. Return the calendar link or None."""
  user = Users.all().filter("google_token = ", token).get()
  calendar = calendar_link or getattr(user, details['link_key'])
  calendar, needs_updating = find_calendar(list_calendars(gcal), l, 
                                           link=calendar, **ascii_keys(details))
  if needs_updating:
    setattr(user, details['link_key'], calendar)
    if not calendar or not calendar_link :
      setattr(user, details['data_key'], None)
    user.put()
  return calendar

def handle_updateevents(task, gcal, token, l):
  """This updates the user's events. It grabs the latest events, checks for 
  anything new and returns a list of tasks to make the needed changes."""
  logging.info('Checking for events to update')
  # Grab the calendar link
  try:
    calendar = lookup_calendar(task.get('calendar'), config.EVENT_CALENDAR,
                               gcal, token, l)
  except RequestError, err:
    return handle_error(task, err, parse_google_error)
  except (DownloadError, urlfetch.Error), err:
    return handle_error(task, err, parse_urlfetch_error)
  else:
    # We can't update a calendar that doesn't exist
    if not calendar:
      return [dict({'type': 'insert-calendar', 'queue': 'fast'},
                   **config.EVENT_CALENDAR), task]

    # Setup an formatting function that knows about the time difference
    # (I can't decide if this is better or worse than throwing the time
    # difference around, either way is kind of crappy, hmm..)
    f = lambda a,b,c,d: format_eventtask(a,b,c,d, task['time-difference'])

    # It's there, update and return the results
    return update_data(task, token, grab_events, f, 'events', calendar, l,
                       event_not_in_past)
    
  
def handle_updatebirthdays(task, gcal, token, l):
  """This updates the users birthdays. It returns a list of tasks needed
  to be completed to bring the user's birthday calendar up to date."""
  logging.info('Checking for birthdays to update')
  # Grab the calendar link
  try:
    calendar = lookup_calendar(task.get('calendar'), config.BIRTHDAY_CALENDAR,
                               gcal, token, l)
  except RequestError, err:
    return handle_error(task, err, parse_google_error)
  except (DownloadError, urlfetch.Error), err:
    return handle_error(task, err, parse_urlfetch_error)
  else:    
    # We can't update a calendar that doesn't exist
    if not calendar:
      return [dict({'type': 'insert-calendar', 'queue': 'slow'},
                   **config.BIRTHDAY_CALENDAR), task]
    # It's there, update and return the results
    return update_data(task, token, grab_birthdays, format_birthdaytask, 
                       'birthdays', calendar, l)

def handle_insert_event(task, gcal, token, l):
  """Take an insert event task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  logging.info("Adding event " + task['title'])
  try:
    event = create_event(task['title'], task['content'], task['start'],
                         task['end'], fb_id=task['fb_id'], 
                         pic=task.get('picture', None),
                         repeat_freq=task.get('repeat', None),
                         location=task.get('location', None))
    gcal.InsertEvent(event, task['calendar'])
    return []
  except RequestError, err:
    return handle_error(task, err, parse_google_error)
  except (DownloadError, urlfetch.Error), err:
    return handle_error(task, err, parse_urlfetch_error)
  
def handle_update_event(task, gcal, token, l):
  """Take an update event task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  # Find the event
  events, search_failed = find_event(gcal, task['calendar'], task,
                                     extended={'+fb_id+':task['fb_id']})
  
  # Search for event failed, return new tasks to be queued
  if search_failed != False:
    return search_failed

  if events:
    for event in events:
      logging.info("Updating event " + str(event.title.text))
      edit_link = event.GetEditLink().href

      event = populate_event(event, task['title'], task['content'], 
                             task['start'], task['end'], fb_id=task['fb_id'], 
                             pic=task.get('picture', None),
                             repeat_freq=task.get('repeat', None),
                             location=task.get('location', None))
      try:
        gcal.UpdateEvent(edit_link, event)
      except RequestError, err:
        return handle_error(task, err, parse_google_error)
      except (DownloadError, urlfetch.Error), err:
        return handle_error(task, err, parse_urlfetch_error)
  else:
    # If event we're updating doesn't exist we should just create it
    logging.info("Event not found to update, creating it instead.")
    task['type'] = 'insert-event'
    return [task]
  return []


def handle_removegoogle(task, gcal, token, l):
  """Task handler to delete a user's google token. Used when it's no longer
  working."""
  user = Users.all().filter("google_token = ", token).get()
  if (user):
    user.google_token = None
    user.status = l("Google token expired.")
    user.put()
    logging.info("Removed Google token for " + str(user.facebook_id))
  return []

def handle_remove_event(task, gcal, token, l):
  """Take a update event task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  # Find the event to remove
  events, search_failed = find_event(gcal, task['calendar'], task,
                                     extended={'+fb_id+':task['fb_id']})

  # Search for event failed, return tasks to run instead
  if search_failed != False:
    return search_failed

  if events:
    for event in events:
      logging.info("Deleting event " + str(event.title.text))
      try:
        gcal.DeleteEvent(event.GetEditLink().href)  
      except RequestError, err:
        return handle_error(task, err, parse_google_error)
      except (DownloadError, urlfetch.Error), err:
        return handle_error(task, err, parse_urlfetch_error)
  else:
    logging.error("Couldn't find event to delete:" + task['fb_id'])
  return []

def handle_update_user(task, gcal, token, l):
  """This handler is used to update a User's calendars and status. It's 
  necessary because refresh_everyones_calendars() was starting to timeout."""
  user = Users.all().filter("google_token = ", token).get()
  if (user):
    logging.info("Updating user's stuff")
    # "Why update timezone every time?" - because people bitch if it's ever
    # even an hour wrong! (and rightly so)
    time_difference, parsed_error = update_timedifference(user=user)
    # Maybe we should update locale here too? The jury's out on that one.
    if parsed_error != False:
      return handle_error(task, action=parsed_error)
    time = (datetime.now(UTC()) + 
            make_timedelta(time_difference)).strftime('%A %d %B %Y - %X')
    user.status = l("Last updated: %s") % time
    user.put()
    return [{'type': 'update-events', 'calendar': user.event_cal,
             'time-difference': time_difference, 'queue': 'slow'},
            {'type': 'update-birthdays', 'calendar': user.bday_cal,
             'queue': 'slow'}]
  else:
    logging.error("Can't find user so can't update them!")
    return []

def refresh_everyones_calendars():
  """This function is used by the /refresh view to refresh everyone's calendars.
  It loops through each user and adds refresh tasks to the task queue."""
  users = Users.all()
  for user in users:
    if user.facebook_token and user.google_token:
      enqueue_tasks([{'type': 'update-user', 'queue': 'fast'}],
                    user.google_token, user.locale)

def lang_get(s, locale, lang):
  """Helper function for translator, it's required because lambda is so limited
  in Python. It just does a .get on the lang dictionary for the s string and
  logs an error if there's no match."""
  # Ok there's this one special case, return the locale name if we ask for it
  if s == 'locale':
    return locale
  # No lang, just log and return
  if not lang:
    #logging.error("No match for '" + s + "' in locale '" + locale + "'")
    return s
  # Grab the result from the language dictionary
  if lang:
    result = lang.get(s,None)
    if not result:
      # No result, just return the un-translated string but log the failure
      #logging.error("No match for '" + s + "' in locale '" + locale + "'")
      return s
    else:
      # Successful translation
      return result

def translator(locale):
  """Take a locale string and return a translation function we can use to 
  translate into the relevant language."""
  if not locale:
    return lambda s:s
  language = translations.languages.get(locale, None)
  return lambda s:lang_get(s, locale, language)

def handle_task(store_key, token, locale):
  """Take a task, given by the task queue worker and deal with it. This requires
  we look up the task's details in the data store, dispatch the correct handler
  and finaly enqueue and future tasks generated in the process."""
  # First we need to grab the task's data from the store
  store = TaskData.get(db.Key(store_key))
  # Nothing in store by that ID, we have to give up :(
  if not store:
    logging.error("Store_key " + store_key + " not found, can't handle task.")
    return
  # Delete the store, we want to keep things nice and tidy
  try:
    task = json.loads(store.data)
    store.delete()
  # If we get an error just recurse round again
  # (I've already checked the store existed, hopefully that's enough..)
  except ApplicationError, err:
    return handle_task(store_key, token, locale)

  # Future tasks is a list of new tasks to enqueue, 
  # generated while we have been dealing with the current tasks
  future_tasks = []
  # Connect to Google calendar
  gcal, parsed_error = check_google_token(token)
  # If there's an error connecting handle the error for each task
  if parsed_error != False:
    future_tasks.extend(handle_error(task, action=parsed_error))
    enqueue_tasks(future_tasks, token, locale)
    return
  # No error but no gcal probably means we should retry later
  elif not gcal:
    enqueue_task(token, locale, task=task)
    return

  # Get translator function
  l = translator(locale)

  # Map task types to handler functions
  handlers = {'insert-calendar': 'handle_insert_calendar',
              'insert-event': 'handle_insert_event',
              'update-event': 'handle_update_event',
              'remove-event': 'handle_remove_event',
              'new-user': 'handle_newuser_event',
              'update-birthdays': 'handle_updatebirthdays',
              'update-events': 'handle_updateevents',
              'remove-google-token': 'handle_removegoogle',
              'update-user': 'handle_update_user'}

  # Deal with the task
  try:
    # Dispatch the task to the appropriate handler
    handler = globals()[handlers.get(task['type'], 'handle_unknown_task')]
    future_tasks.extend(handler(task, gcal, token, l))
  except Exception, err:
    # Catch any exception, this is to stop Google retrying the task like mad
    logging.error('Handler for ' + task.get('type','') + ' Failed!\n' +
                  'Error: ' + str(err) + '\n' +
                  'Task: ' + str(task) + '\n' +
                  'Locale: ' + str(locale))
    logging.debug('Error details:' + str(dir(err)))
    logging.debug('Traceback: ' + str(traceback.format_stack()))
    logging.debug('Traceback: ' + str(traceback.format_exc()))

  # Enqueue any future tasks we need to deal with
  enqueue_tasks(future_tasks, token, locale)

def delay_tasks(message="hoooooooooooooolllllld-up! brap brap brap"):
  """When we receive a 'quota depleated' error we need to put everything on
  hold. For now we just stall by 1 day, maybe we will make this smarter in
  the future?"""
  logging.info(message)
  tomorrow = datetime.today() + timedelta(days=1)
  set_flag('next-task-run-date', tomorrow.strftime('%Y-%m-%dT%H:%M:%S.000Z'))

def handle_insert_calendar(task, gcal, token, l):
  """Take an insert calendar task and deal with it. Return a list of tasks to
  perform later or an empty list."""
  logging.info("Adding calendar " + task['title'])

  # Check that it doesn't already exist
  calendar = lookup_calendar(None, task, gcal, token, l)
  if calendar:
    logging.info("Didn't create calendar " + task['title'] +
                 "because it already exists.")
    return []

  # OK it doesn't let's add it
  try:
    new_cal = create_calendar(gcal, l(task['title']), l(task['description']))
  except RequestError, err:
    return handle_error(task, err, parse_google_error)
  except (DownloadError, urlfetch.Error), err:
    return handle_error(task, err, parse_urlfetch_error)
  else:
    # Record the calendar in the user's datastore
    user = Users.all().filter("google_token =", token).get()
    setattr(user, task['link_key'], new_cal.content.src)
    setattr(user, task['data_key'], None)
    user.put()
    return []
  
def handle_unknown_task(task, gcal, token, l):
  logging.info('Unknown task type "' + task['type'] + '"')
  return []

def check_facebook_scope(permissions, token=None, graph=None):
  """Take a list of permissions and return a list of permissions that are
  present. It uses the graph api to run a FQL query."""
  # Make sure we've got a graph connection
  if not graph:
    graph = facebook.GraphAPI(token)
  # Craft and run the query
  scope = ",".join(permissions)
  query = 'SELECT ' + scope + ' FROM permissions WHERE uid=me()'
  try:
    results = graph.fql(query)
  except GraphAPIError, err:
    return None, parse_facebook_error(err)
  except urlfetch.Error, err:
    return None, parse_urlfetch_error(err)
  # If we have results return them
  if results and len(results) and type(results).__name__ == 'list':
    return [k for k in results[0] if results[0][k]], False
  else:
    return [], False

def facebook_scope_is(permissions, token=None, graph=None):
  """Take a list of permissions and return True if they are all present or
  False if they are not. (Ignores extra permissions.)"""
  actual_permissions, parsed_error = check_facebook_scope(permissions, 
                                                          token=token, 
                                                          graph=graph)
  if parsed_error != False:
    return None, parsed_error
  if actual_permissions == permissions:
    return True, False
  else:
    return False, False

def decode_signed_request(signed_request):
  """Take the signed request and return the id and token."""
  data = facebook.parse_signed_request(signed_request,
                                       config.FACEBOOK_APP_SECRET)
  if data:
    return data.get('user_id', None), data.get('oauth_token', None)
  else:
    return None, None

def facebook_connect(facebook_id, facebook_token, permissions):
  "Take the details from Facebook and return the User object or None"""
  # First check there is a token and ID
  if not facebook_id or not facebook_token:
    logging.info('FBID or TOKEN MISSING - New user?')
    return None, False
  # Next check they have all the required permissions
  graph = facebook.GraphAPI(facebook_token)
  needed_perms, parsed_error = facebook_scope_is(permissions, graph=graph)
  if parsed_error != False:
    return None, parsed_error
  if not needed_perms:
    user = None
  else:
    # Good now let's see if they are in our database
    user = Users.all().filter("facebook_id =", facebook_id).get()
    if user:
      # They are, let's make sure their Facebook token is up to date
      if facebook_token != user.facebook_token:
        user.facebook_token = facebook_token
        user.put()
    else:
      # They aren't in our database, add 'um!
      locale, parsed_error = check_locale(facebook_token=facebook_token)
      if parsed_error != False:
        logging.error("Oh sheeeiiit!11!one!")
        return None, parsed_error
      user = Users(facebook_id=facebook_id,
                   facebook_token=facebook_token,
                   locale=locale,
                   status='Connected to Facebook.')
      user.put() 
      # Todo - status should be translated, but we don't know locale
  return user, False

def gcal_connect(user, token):
  """Take a user and a google token parameter. Return a google connection if
  connected or None."""
  l = translator(user.locale)
  gcal = None
  if user.google_token:
    # Already registered, make sure existing token is valid
    gcal, parsed_error = check_google_token(user.google_token)
    if parsed_error != False:
      return None, parsed_error
  if not gcal:
    # It's not, let's see if they have passed a good token
    if token:
      gcal = upgrade_google_token(token)
      if gcal:
        # New user, update their shit
        user.status = l('Connected to Google Calendar.')
        user.google_token = gcal.GetAuthSubToken()
        user.put()
        enqueue_tasks([{'type': 'new-user', 'queue': 'fast'}],
                      user.google_token, user.locale)
  return gcal, False

def quota_status():
  quota_used_up =  we_gotta_wait()
  if quota_used_up:
    return (l("CalenDerp has used up its Google quota, %s") % 
            str(quota_used_up))

def user_connection_status(signed_request, google_token, permissions):
  # Init the vars to pass back
  error = False
  facebook_connected = False
  google_connected = False
  status = ""
  locale = None
  # Decode the signed_request data from Facebook
  facebook_id, facebook_token = decode_signed_request(signed_request)
  # See if we are connected properly, with the proper permissions
  user, parsed_error = tackle_retrys(lambda: facebook_connect(facebook_id, 
                                                              facebook_token,
                                                              permissions),
                                     return_error=True)
  if parsed_error:
    logging.error("WE GOT AN ERROR CONNECTING THE USER, DEBUG THIS!")
    tackle_error(parsed_error, google_token, locale)
    error = True

  # Now check results, test Google token too
  if user:
    locale = user.locale
    status = user.status
    facebook_connected = True
    gcal, parsed_error = tackle_retrys(lambda: gcal_connect(user, google_token),
                                return_error=True)
    if parsed_error != False:
      logging.error("GOOGLE ERROR CONNECTING THE USER, DEBUG THIS! ("
                    + str(parsed_error) + ")")
      tackle_error(parsed_error, google_token, locale)
      error = True
    elif gcal:
      google_connected = True

  l = translator(locale)

  # Finaly return something simple for the view to use
  return {'google': google_connected, 'error': error, 'l': l,
          'facebook': facebook_connected, 'status': quota_status() or status}
