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
    google_token = self.request.get("token")
    
    # If not within Facebook frame we need to redirect them
    if not signed_request:
      self.redirect(config.FACEBOOK_APP_URL)

    connection_status = calenderp.user_connection_status(signed_request,
                                                         google_token,
                                                         config.FACEBOOK_SCOPE)
    # We dun goofed! Tell the user to refresh
    if connection_status['error'] == True:
      args = {}
      page = 'vague_error.html'
      
    # Facebook app is installed
    if connection_status['facebook'] == True:
      # Connected to Google Calendar
      if connection_status['google'] == True:
        args = {'status': connection_status['status']}
        page = 'show_status.html'
      # Not connected to Google Calendar yet
      else:
        args = {'login_link': calenderp.GetAuthSubUrl(config.FACEBOOK_APP_URL)}
        page = 'google_login.html'
    # Facebook app isn't installed yet
    else:
      install_link = facebook.oauth_URL(client_id=config.FACEBOOK_APP_ID, 
                                        redirect_uri=config.FACEBOOK_APP_URL,
                                        scope=",".join(config.FACEBOOK_SCOPE),
                                        display="page")
      args = {'install_link': install_link}
      page = 'install.html' 
    # Either way render the page :)
    path = os.path.join(os.path.dirname(__file__), page);
    self.response.out.write(template.render(path, args))
