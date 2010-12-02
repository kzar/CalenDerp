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
import config, calenderp, logging, os, facebook,sys
from django.utils import simplejson as json
from google.appengine.ext import webapp

# Import mako for more sensible templates
sys.path.insert(0, 'mako.zip')
from mako.template import Template

class worker(webapp.RequestHandler):
  """Handles /worker requests which processes the work from task queue"""
  def post(self):
    # Grab the parameters
    store_key = self.request.get("store_key")
    token = self.request.get("token")
    locale = self.request.get("locale")
    # Check if we can run now or if we have to wait
    if calenderp.we_gotta_wait():
      # Quota is used up, stall everything
      queue = self.request.headers['X-AppEngine-QueueName']
      calenderp.delay_task(store_key, token, locale, queue)
    else: 
      # Good to go, do the work!
      calenderp.handle_task(store_key, token, locale)
    
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
      page = 'templates/vague_error.html'
      
    # Facebook app is installed
    if connection_status['facebook'] == True:
      # Connected to Google Calendar
      if connection_status['google'] == True:
        args = {'status': connection_status['status']}
        page = 'templates/show_status.html'
      # Not connected to Google Calendar yet
      else:
        args = {'login_link': calenderp.GetAuthSubUrl(config.FACEBOOK_APP_URL)}
        page = 'templates/google_login.html'
    # Facebook app isn't installed yet
    else:
      install_link = facebook.oauth_URL(client_id=config.FACEBOOK_APP_ID, 
                                        redirect_uri=config.FACEBOOK_APP_URL,
                                        scope=",".join(config.FACEBOOK_SCOPE),
                                        display="page")
      args = {'install_link': install_link}
      page = 'templates/install.html' 
    
    # Now render the page :)
    args['l'] = connection_status['l']
    template = Template(filename=page)
    render = template.render_unicode(**args)
    self.response.out.write(render)

