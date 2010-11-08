FACEBOOK_APP_ID = "xXxXxXxXxXx"
FACEBOOK_APP_SECRET = "xXxXxXxXxXx"
FACEBOOK_APP_URL = "http://apps.facebook.com/calenderp/"
FACEBOOK_SCOPE = ["offline_access", "friends_birthday", "user_events"]

BIRTHDAY_CALENDAR = {'title': 'Birthdays', 'link_key': 'bday_cal', 
                     'data_key': 'birthdays', 
                     'description': 'Facebook friend birthdays'}
EVENT_CALENDAR = {'title': 'Events', 'link_key': 'event_cal',
                  'data_key': 'events',
                  'description': 'Facebook events'}

GOOGLE_QUERY_RETRYS = 5

GOOGLE_ERRORS = [{'code': '302L', 
                  'reason': 'Redirect received, but redirects_remaining <= 0',
                  'action': 'retry',
                  'explanation': 'Query temporarily failed, retry.'},
                 {'code': '403L',
                  'reason': 'Bad Request',
                  'action': 'give-up',
                  'explanation': 'Query was fucked, investigate why!'},
                 {'code': '403L',
                  'reason': 'Non 200 response on upgrade',
                  'action': 'give-up',
                  'explanation': 'Failed to setup token, user not authed.'}]
