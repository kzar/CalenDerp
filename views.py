import config, calenderp, logging, os, facebook
from django.utils import simplejson as json
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

class worker(webapp.RequestHandler):
  """Handles /worker requests which processes the work from task queue"""
  def post(self):
    # Grab the parameters
    tasks = json.loads(self.request.get("tasks"))
    token = self.request.get("token")

    if calenderp.we_gotta_wait():
      # Quota is used up, stall everything
      calenderp.enqueue_tasks(tasks, token)
    else: 
      # Good to go, do the work!
      calenderp.handle_tasks(tasks, token)
    
class refresh(webapp.RequestHandler):
  def get(self):
    if calenderp.we_gotta_wait():
      # Quota's used up, don't do anything
      logging.info("Refreshing is on hold, we've used our quota :(")
    else:
      # Good to go, refresh those calendars!
      logging.info("Refreshing everyone's calendars!")
      calenderp.refresh_everyones_calendars()
      
class MainPage(webapp.RequestHandler):
  def get(self):
    # Check if we are connected with Facebook and Google
    signed_request = self.request.get("signed_request")
    connection_status = calenderp.user_connection_status(signed_request)

    # Facebook app is installed
    if connection_status['facebook'] == True:
      # Connected to Google Calendar
      if connection_status['google'] == True:
        args = {'status': connection_status['status']}
        page = 'show_status.html'
      # Not connected to Google Calendar yet
      else:
        args = {'login_link': GetAuthSubUrl(config.FACEBOOK_APP_URL)}
        page = 'google_login.html'
    # Facebook app isn't installed yet
    else:
      scope = "offline_access,friends_birthday,user_events"
      install_link = facebook.oauth_URL(client_id=config.FACEBOOK_APP_ID, 
                                        redirect_uri=config.FACEBOOK_APP_URL,
                                        display="page", scope=scope)
      args = {'install_link': install_link}
      page = 'install.html' 
    # Either way render the page :)
    path = os.path.join(os.path.dirname(__file__), page);
    self.response.out.write(template.render(path, args))
