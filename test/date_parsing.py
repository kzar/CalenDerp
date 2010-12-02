import sys
sys.path.append('../')

import unittest, calenderp
from mock import Mock
from gaetestbed import DataStoreTestCase

# Some test data
birthdays = {"data": [
      {
         "link": "http://www.facebook.com/profile.php?id=10000",
         "name": "Laura Hines",
         "id": "10000",
         "picture": "http://profile.ak.fbcdn.net/1.jpg"
      },
      {
         "link": "http://www.facebook.com/james.humphry",
         "birthday": "04/14/1984",
         "name": "James Humphry",
         "id": "20000",
         "picture": "http://profile.ak.fbcdn.net/2.jpg"
      },
      {
         "link": "http://www.facebook.com/profile.php?id=30000",
         "birthday": "09/12",
         "name": "Patrick McMinn",
         "id": "30000",
         "picture": "http://profile.ak.fbcdn.net/3.jpg"
      },
      {
         "link": "http://www.facebook.com/profile.php?id=40000",
         "name": "Louise Box",
         "id": "40000",
         "picture": "http://profile.ak.fbcdn.net/4.jpg"
      }
]}


class date_parse_testcase(DataStoreTestCase, unittest.TestCase):
    def test_valid_birthday(self):
        # Invalid dates
        self.assertFalse(calenderp.valid_birthday(1,13))
        self.assertFalse(calenderp.valid_birthday(2, 30))
        # Valid date
        self.assertEqual(calenderp.valid_birthday(2, 10), (2, 10))
    def test_parse_birthday(self):
        # Valid dates
        self.assertEqual(calenderp.parse_birthday("08/04/1986"), (4, 8))
        self.assertEqual(calenderp.parse_birthday("02/28"), (28, 2))
        # Invalid dates
        self.assertFalse(calenderp.parse_birthday("2010/02/2"))
        self.assertFalse(calenderp.parse_birthday("12/35/2007"))
        self.assertFalse(calenderp.parse_birthday("15/-1/1992"))
        self.assertFalse(calenderp.parse_birthday("Blahdy blah"))
    def test_grab_birthdays(self):
        # Blank user
        self.assertRaises(AttributeError, calenderp.grab_birthdays, None)

        # Test the function as best we can (Not terribly useful I fear.)
        # Mock the Facebook stuff
        bdays = calenderp.facebook.GraphAPI.get_object = Mock()
        bdays.return_value = birthdays
        # Setup a pretend user
        user = calenderp.Users(facebook_id="12345",
                               facebook_token="ABC32423",
                               locale="en_GB",
                               status='Connected to Facebook.')
        # Get the results and check some of them
        results, error = calenderp.grab_birthdays(user)
        self.assertEqual(len(results), 2)
        self.assertFalse(error)
        self.assertEqual(results[0]['day'], 14)
        self.assertEqual(results[0]['month'], 4)
        self.assertEqual(results[0]['pic'], "http://profile.ak.fbcdn.net/2.jpg")
        self.assertEqual(results[0]['id'], "20000")
        self.assertEqual(results[0]['name'], "James Humphry")
        self.assertEqual(results[1]['day'], 12)
        self.assertEqual(results[1]['month'], 9)
        self.assertEqual(results[1]['pic'], "http://profile.ak.fbcdn.net/3.jpg")
        self.assertEqual(results[1]['id'], "30000")
        self.assertEqual(results[1]['name'], "Patrick McMinn")        
