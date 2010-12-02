import sys
sys.path.append('../')

import unittest, calenderp
from mock import Mock
from gaetestbed import DataStoreTestCase
from models import Users

def cal_link(code):
    """Saves my eyes heh"""
    return 'http://www.google.com/calendar/feeds/' + code + '/private/full'

calendars = [{'title': 'user@main.com',
              'description': '',
              'link': cal_link("somecodeblah-user@main.com")},
             {'title': 'Birthdays',
              'description': 'Facebook friend birthdays',
              'link': cal_link("herpderp-birthdays")},
             {'title': 'Events',
              'description': 'Facebook events',
              'link': cal_link("herpderp-events")}]

class task_handlers_testcase(DataStoreTestCase, unittest.TestCase):
    def test_handle_newuser_event(self):
        new_user = calenderp.handle_newuser_event(None, None, None, None)
        self.assertEqual(len(new_user), 3)
        self.assertEqual(new_user[0]['type'], 'insert-calendar')
        self.assertEqual(new_user[0]['title'], 'Birthdays')
        self.assertEqual(new_user[0]['link_key'], 'bday_cal')
        self.assertEqual(new_user[0]['data_key'], 'birthdays')
        self.assertEqual(new_user[1]['type'], 'insert-calendar')
        self.assertEqual(new_user[1]['title'], 'Events')
        self.assertEqual(new_user[1]['link_key'], 'event_cal')
        self.assertEqual(new_user[1]['data_key'], 'events')
        self.assertEqual(new_user[2]['type'], 'update-user')
    def test_handle_updateevents(self):
        # Make sure test datastore is empty
        self.assertEqual(Users.all().count(), 0)
        # Now add a user for testing
        user = Users(facebook_id="123456",                     
                     facebook_token="blahblahtoken",
                     google_token="herpderptoken",
                     locale="en_GB",
                     status='Test user status.',
                     event_cal=calendars[2]['link'])
        user.put()
        # Make sure the test entry is in
        self.assertEqual(Users.all().count(), 1)
        # Mock list_calendars
        list_calendars = calenderp.list_calendars = Mock()
        list_calendars.return_value = calendars
        # Mock update_data (This function needs proper testing elsewhere!)
        update_data = calenderp.update_data = Mock()
        update_data.return_value = "some data"
        # Setup a translator
        l = calenderp.translator(user.locale)
        # Test it with a known calendar
        task = {'time-difference': None, 'calendar': calendars[2]['link']}
        result = calenderp.handle_updateevents(task, None, 
                                               "herpderptoken", l)
        #self.assertEqual(self.query_count, 2)
        self.assertEqual(result, 'some data')
        # Test it by looking up calendar in datastore
        task = {'time-difference': None}
        result = calenderp.handle_updateevents(task, None, 
                                               "herpderptoken", l)
        self.assertEqual(result, 'some data')
        # Test it by looking up calendar by description
        user.event_cal = None
        user.put()
        task = {'time-difference': None}
        result = calenderp.handle_updateevents(task, None, 
                                               "herpderptoken", l)
        # Todo - query_count is returning 0 always, figure that out and use it
        # self.assertEqual(self.query_count, 2)
        self.assertEqual(result, 'some data')
        # Test it with no avaliable calendar
        list_calendars.return_value = []
        task = {'time-difference': None}
        result = calenderp.handle_updateevents(task, None, 
                                               "herpderptoken", l)
        self.assertEqual('insert-calendar', result[0]['type'])
        self.assertEqual('Events', result[0]['title'])
