import views
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

application = webapp.WSGIApplication(
                                     [('/', views.MainPage),
                                      ('/worker', views.worker)],
                                     debug=True)

def handleError(error):
    # FIXME write this!
    print "Herp Derp, we got an error"

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
