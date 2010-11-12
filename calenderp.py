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

import os, sys, re, facebook, logging, config, translations, traceback
from google.appengine.api import users, urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.ext import db
from google.appengine.api.urlfetch import DownloadError
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

class Flags(db.Model):
  flag_key = db.StringProperty(required=True)
  value = db.StringProperty(required=True)

def parse_google_error(err):
  """Take a Google error and return an action like 'retry' or 'give-up' based
  on the error. Still needs work."""
  # What about these?! apiproxy_errors.OverQuotaError:

  # Log the error
  logging.debug("Google error: " + str(err))

  # I have no example of a quota error so I'll bodge this check for now:
  if 'quota' in str(err):
    logging.error('QUOTA ERROR!!')
    delay_tasks()
    return 'retry'

  # Get the error's details from the exception object
  error_code = err[0]['status']
  error_message = err[0]['body']
  error_reason = err[0]['reason']

  # Make a dict of errors to check against 
  # (Have to use reason, status code not specic enough :-( )
  error_lookup = {}
  for e in config.GOOGLE_ERRORS:
    error_lookup[e['reason']] = e

  # Lookup the error's reason, this tells us exactly what to do
  match = error_lookup.get(error_reason, None)
  
  # If we know what to do tell them, if not give up
  if match:
    logging.info(match['explanation'])
    return match['action']
  else:
    logging.error('Can\'t handle this error properly, it\'s unknown!')    
    return 'give-up'

def handle_google_error(err, task):
  """Helper function to make handling Google errors within handlers easier.
  Takes an error and the task being processed and returns a list of tasks to
  perform."""
  # First make sure there are any retrys left for the task
  retrys = task.get('retrys', config.GOOGLE_QUERY_RETRYS)
  if (retrys < 1):
    logging.error('We ran out of retrys for this task!')
    return []
  # Now figure out what action should be taken
  action = parse_google_error(err)  
  # OK now do it..
  if action == 'retry':
    logging.info(str(retrys) + ' retrys left.')
    task['retrys'] = retrys - 1
    return [task]
  if action == 'give-up':
    return []
  if action == 'remove-google-token':
    return [{'type': 'remove-google-token'}]

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
  attending = graph.get_object("me/events/attending", fields=fields)
  maybe = graph.get_object("me/events/maybe", fields=fields)
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
  except apiproxy_errors.OverQuotaError:
    delay_tasks()
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
          'fb_id': birthday['id'], 'calendar': calendar, 'repeat': 'YEARLY'}

def format_eventtask(event, task_type, calendar, l):
  """Helpful function to take an event and return a task ready to be
  put in the task queue."""
  # Adjust the mangled dates Facebook gives us
  start = parse_date(event['start'], PT()).astimezone(UTC())
  end = parse_date(event['end'], PT()).astimezone(UTC())
  # Put them into the format Google wants
  start = start.strftime('%Y-%m-%dT%H:%M:%S.000Z')
  end = end.strftime('%Y-%m-%dT%H:%M:%S.000Z')
  # Now return the task
  return {'type': task_type, 'title': event['name'], 'calendar': calendar, 
          'content': event['content'], 'start': start, 'end': end, 
          'fb_id': event['id'], 'location': event['location']}


def check_locale(user=None, google_token=None):
  """Take a google token, look up the user and return the locale. If we don't
  know their locale yet then ask Facebook and record it."""
  logging.info('Checking user\'s locale.')
  if not user:    
    user = Users.all().filter("google_token = ", google_token)[0]

  # Check we don't already know user's locale
  if user.locale:
    return user.locale
  else:
    # We don't so ask Facebook
    graph = facebook.GraphAPI(user.facebook_token)  
    results = graph.get_object("me", fields='locale')
    
    locale = results['locale']
    if locale:
      # We know now, record in database
      logging.info('Locale updated')
      user.locale = locale
      user.put()     
    return locale

def enqueue_tasks(updates, token, locale, chunk_size=5):
  """Take a list of updates and add them to the Task Queue."""
  # Make sure we've got their locale
  if not locale:
    locale = check_locale(google_token=token)

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
                          'token': token,
                          'locale': locale},
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
  except (DownloadError, RequestError), err:
    return [], handle_google_error(err,task)
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
  return [dict({'type': 'insert-calendar'}, **config.BIRTHDAY_CALENDAR),
          dict({'type': 'insert-calendar'}, **config.EVENT_CALENDAR),
          {'type': 'update-events'},
          {'type': 'update-birthdays'}]

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

def update_data(google_token, grab_function, format_function, datastore_key, 
                calendar, l, delete_check=lambda entry: True):
  """Take all the details needed to update a user's data. This is kept generic
  so we can use it to update both birthdays and events. Return a list of tasks
  that need to be carried out to perform the update."""
  # Find the user in the database
  user = Users.all().filter("google_token =", google_token)[0]

  # Make sure there's a Facebook token!
  if not user.facebook_token:
    return []

  # Grab the data from Facebook
  try:
    data = grab_function(user)
  except GraphAPIError, err:
    if 'access token' in str(err): 
      logging.info('User\'s Facebook token expired, clearing it.')
      user.facebook_token = ""
      user.status = l("Facebook connection broken.")
      user.put()
      return []
    else:
      logging.info('Some error doing Facebook query:' + str(err))
      return []

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
    description = str(calendar.summary and calendar.summary.text)
    calendars.append({'title': calendar.title.text,
                      'description': description,
                      'link': calendar.GetAlternateLink().href})
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
      if calendar['description'] == l(description):
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
  user = Users.all().filter("google_token = ", token)[0]
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
  
  # TODO
  # Track down Application error 5 that's coming from this task handler somewhere 
  
  # Grab the calendar link
  try:
    calendar = lookup_calendar(task.get('calendar'), config.EVENT_CALENDAR,
                               gcal, token, l)
  except (RequestError, DownloadError), err:
    return handle_google_error(err,task)
  else:
    # We can't update a calendar that doesn't exist
    if not calendar:
      return [dict({'type': 'insert-calendar'}, **config.EVENT_CALENDAR), task]

    # It's there, update and return the results
    return update_data(token, grab_events, format_eventtask, 'events', 
                       calendar, l, event_not_in_past)
  
def handle_updatebirthdays(task, gcal, token, l):
  """This updates the users birthdays. It returns a list of tasks needed
  to be completed to bring the user's birthday calendar up to date."""
  logging.info('Checking for birthdays to update')
  # Grab the calendar link
  try:
    calendar = lookup_calendar(task.get('calendar'), config.BIRTHDAY_CALENDAR,
                               gcal, token, l)
  except (RequestError, DownloadError), err:
    return handle_google_error(err,task)
  else:    
    # We can't update a calendar that doesn't exist
    if not calendar:
      return [dict({'type': 'insert-calendar'}, **config.BIRTHDAY_CALENDAR),
              task]
    # It's there, update and return the results
    return update_data(token, grab_birthdays, format_birthdaytask, 
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
  except (DownloadError, RequestError), err:
    return handle_google_error(err, task)
  
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
      except (DownloadError, RequestError), err:
        return handle_google_error(err, task)
  else:
    logging.error("Couldn't find event to update:" + task['fb_id'])
  return []


def handle_removegoogle(task, gcal, token, l):
  """Task handler to delete a user's google token. Used when it's no longer
  working."""
  user = Users.all().filter("google_token = ", token).get()
  if (user):
    user.google_token = None
    user.status = "Google token expired."
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
      except (DownloadError, RequestError), err:
        return handle_google_error(err, task)
  else:
    logging.error("Couldn't find event to delete:" + task['fb_id'])
  return []

def refresh_everyones_calendars():
  """This function is used by the /refresh view to refresh everyone's calendars.
  It loops through each user and adds refresh tasks to the task queue."""
  users = Users.all()
  time = datetime.now().strftime('%A %d %B %Y - %X')
  for user in users:
    if user.facebook_token and user.google_token:
      # Get the locale
      if not user.locale:
        locale = check_locale(user=user)
      else:
        locale = user.locale
      l = translator(locale)
      # Update their status. (I know, a little misleading time-wise.)      
      user.status = l("Last updated: %s") % time
      user.put()
      # Setup the tasks
      tasks = [{'type': 'update-events', 'calendar': user.event_cal},
               {'type': 'update-birthdays', 'calendar': user.bday_cal}]
      # Run the tasks
      enqueue_tasks(tasks, user.google_token, user.locale)

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

def handle_tasks(tasks, token, locale):
  """This function is used by the /worker view to actually do all the work given
  in the task queue."""
  # Connect to Google calendar
  gcal = check_google_token(token)
  if not gcal:
      # Probably because we're out of quota for the URL fetch so just enqueue
      enqueue_tasks(tasks, token, locale)
      return

  # Get translator function
  l = translator(locale)

  # Future tasks is a list of new tasks to enqueue, 
  # generated while we have been dealing with the current tasks
  future_tasks = []

  # Map task types to handler functions
  handlers = {'insert-calendar': 'handle_insert_calendar',
              'insert-event': 'handle_insert_event',
              'update-event': 'handle_update_event',
              'remove-event': 'handle_remove_event',
              'new-user': 'handle_newuser_event',
              'update-birthdays': 'handle_updatebirthdays',
              'update-events': 'handle_updateevents',
              'remove-google-token': 'handle_removegoogle'}

  # Deal with the tasks
  for task in tasks:
    handler = globals()[handlers.get(task['type'], 'handle_unknown_task')]
    try:
      # Dispatch the task to the appropriate handler
      future_tasks.extend(handler(task, gcal, token, l))
    except Exception, err:
      # Catch any exception, this is to stop Google retrying the task like mad
      logging.error('Handler for ' + task['type'] + ' Failed!\n' +
                    'Error: ' + str(err) + '\n' +
                    'Task: ' + str(task) + '\n' +
                    'Locale: ' + str(locale))
      logging.debug('Error details:' + str(dir(err)))
      logging.debug('Traceback: ' + str(traceback.format_stack()))

  # Enqueue any future tasks we need to deal with
  enqueue_tasks(future_tasks, token, locale)

def delay_tasks(message="hoooooooooooooolllllld-up! brap brap"):
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
  except (RequestError, DownloadError), err:
    return handle_google_error(err,task)
  else:
    # Record the calendar in the user's datastore
    user = Users.all().filter("google_token =", token)[0]      
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
  results = graph.fql(query)
  # If we have results return them
  if results and len(results) and type(results).__name__ == 'list':
    return [k for k in results[0] if results[0][k]]
  else:
    return []

def facebook_scope_is(permissions, token=None, graph=None):
  """Take a list of permissions and return True if they are all present or
  False if they are not. (Ignores extra permissions.)"""
  actual_permissions = check_facebook_scope(permissions, token=token, 
                                            graph=graph)
  logging.info('perm:' + ','.join(actual_permissions))
  logging.info('needed perm:' + ','.join(permissions))
  if actual_permissions == permissions:
    return True
  else:
    return False

def decode_signed_request(signed_request):
  """Take the signed request and return the id and token."""
  data = facebook.parse_signed_request(signed_request,
                                       config.FACEBOOK_APP_SECRET)
  if data:
    return data.get('user_id', None), data.get('oauth_token', None)
  else:
    return None, None

def fb_connect(facebook_id, facebook_token, permissions):
  "Take the details from Facebook and return the User object or None"""
  if facebook_id and facebook_token:
    # First check they have all the required permissions
    graph = facebook.GraphAPI(facebook_token)
    if facebook_scope_is(permissions, graph=graph):
      # Good now let's see if they are in our database
      user = Users.all().filter("facebook_id =", facebook_id).get()
      if user:
        # They are, let's make sure their Facebook token is up to date
        if facebook_token != user.facebook_token:
          user.locale = check_locale(user=user)
          user.facebook_token = facebook_token
          user.put()
      else:
        # They aren't in our database, add 'um!
        user = Users(facebook_id=facebook_id,
                     facebook_token=facebook_token,
                     status='Connected to Facebook.')
        user.put()
    else:
      # They don't have proper permissions, ignore them!
      user = None
    return user

def facebook_connect(facebook_id, facebook_token, permissions, retrys=5):
  """Recursively call fb_connect to connect the user. Catch all errors and log
  them so that they aren't given to the user. After the retrys are used up 
  give up and return an error."""
  if retrys < 1:
    return True, None
  else:
    try:
      error = False
      user = fb_connect(facebook_id, facebook_token, permissions)
    except Exception, err:
      logging.error('Checking user connection status Failed!\n' + 
                    'Error: ' + str(err) + 
                    ' (' + str(retrys) + ' retrys left)')
      error, user = facebook_connect(facebook_id, facebook_token, 
                                     permissions, retrys - 1)
  return error, user

def gcal_connect(user, token):
  """Take a user and a google token parameter. Return a google connection if
  connected or None."""
  l = translator(user.locale)
  gcal = None
  if user.google_token:
    # Already registered, make sure existing token is valid
    gcal = check_google_token(user.google_token)
  if not gcal:
    # It's not, let's see if they have passed a good token
    if token:
      gcal = upgrade_google_token(token)
      if gcal:
        # New user, update their shit
        user.status = l('Connected to Google Calendar.')
        user.google_token = gcal.GetAuthSubToken()
        user.put()
        enqueue_tasks([{'type': 'new-user'}], user.google_token, user.locale)
  return gcal

def quota_status():
  quota_used_up =  we_gotta_wait()
  if quota_used_up:
    return (l("CalenDerp has used up its Google quota, %s") % 
            str(quota_used_up))

def user_connection_status(signed_request, google_token, permissions):
  # Init the vars to pass back
  facebook_connected = False
  google_connected = False
  status = ""
  locale = None

  # Todo
  # Fix problems installing a few users are having.
  # (Somehow facebook_connect is not returning a user when really it should.)

  # Decode the signed_request data from Facebook
  facebook_id, facebook_token = decode_signed_request(signed_request)
  # See if we are connected properly, with the proper permissions
  error, user = facebook_connect(facebook_id, facebook_token, permissions)
  # Now check results, test Google token too
  if user:
    locale = user.locale
    status = user.status
    facebook_connected = True
    if gcal_connect(user, google_token):
      google_connected = True

  l = translator(locale)

  # Finaly return something simple for the view to use
  return {'google': google_connected, 'error': error, 'l': l,
          'facebook': facebook_connected, 'status': quota_status() or status}
