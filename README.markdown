![Alt text](http://calenderp.appspot.com/images/calenderp.png)

About
-----

CalenDerp is a Facebook app that lets you put all your birthdays and events into Google Calendar. I wrote the application out of frustration when none of the existing apps I tried worked. 

It's a work in progress, there are a lot of things I want to change but it's starting to get there.

It works using a combination of Google's appengine, Google Calendar API, Facebook's Graph API and Python. Once you are authed with both Facebook and Google, CalenDerp queues up all the work in the task queue and syncs your calendars. Once every 30 mins the calendars are refreshed using a cronjob.

Anyway give it a try: <http://apps.facebook.com/calenderp/>

Todo
----
 - Figure out how to avoid passing long event descriptions around, through through the task queue etc. How can we do this whilst avoiding lots more Facebook API requests asking for the description? (Storing a hash would work but then it would require me to ask Facebook for the description each and every time I add or update an event.)
 - Figure out how to to avoid hitting AppEngine's "simultaneous dynamic request limit". This is REALLY important because as more users install the app it's becoming a real problem. (Google will only scale your application so far if requests take longer than 1 second but unfortunately most of my requests to the Google calendar API seem to blow that out of the water :(! )
 - Add translations for more languages.
 - Write a test suite, I should have done this a lot earlier as the application is getting fairly complicated and developing it blind is insane. (I'm proud though it all works really well.)
 - Update all of the function's documentation strings, as I've refactored the code the documentation strings have started to get a bit out of sync with the actual code.
 - Figure out how to get locale for user before they have installed the Facebook application, that will let us display install.html in their native language.

License
-------
Unless otherwise specified, Copyright Dave Barker 2010.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
