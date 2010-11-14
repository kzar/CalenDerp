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

QUERY_RETRYS = 5

FACEBOOK_ERRORS = [{'code': 190, 
                    'reason': 'Invalid OAuth 2.0 Access Token',
                    'explanation': 'Facebook token broken, removing it.',
                    'action': 'remove-facebook-token'},
                   {'code': 'OAuthException',
                    'reason': 'Invalid OAuth access token.',
                    'explanation': 'Facebook token broken, removing it.',
                    'action': 'remove-facebook-token'}]

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
                  'explanation': 'Failed to setup token, user not authed.'},
                 {'code': '403L',
                  'reason': 'Forbidden',
                  'body': 'You must be a calendar user to use private feeds.',
                  'action': 'remove-google-token',
                  'explanation': 'Google token broken, removing it.'},
                 {'code': '500L',
                  'reason': 'Internal Server Error',
                  'body': 'Service error: could not insert entry',
                  'action': 'retry',
                  'explanation': 'Google dun goofed, retry!'},
                 {'reason': 'ApplicationError: 1',
                  'action': 'give-up',
                  'explanation': 'URL fetch was given an invalid URL!'},
                 {'reason': 'ApplicationError: 2',
                  'action': 'give-up',
                  'explanation': 'URL fetch failed.'},
                 {'reason': 'ApplicationError: 3',
                  'action': 'give-up',
                  'explanation': 'URL fetch gave "UNSPECIFIED ERROR"?!'},
                 {'reason': 'ApplicationError: 4',
                  'action': 'give-up',
                  'explanation': 'URL gave "RESPONSE TOO LARGE"?!'},
                 {'reason': 'ApplicationError: 5',
                  'action': 'retry',
                  'explanation': 'URL fetch timed out, retry.'}]
