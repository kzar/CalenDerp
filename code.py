import views
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

application = webapp.WSGIApplication(
                                     [('/', views.MainPage),
                                      ('/wishes', views.wishes),
                                      ('/gcal', views.gcal),
                                      ('/worker', views.worker),
                                      (r'/feed/(.+)', views.view_feed)],
                                     debug=True)

def handleError(error):
    # FIXME write this!
    print "Herp Derp, we got an error"

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
