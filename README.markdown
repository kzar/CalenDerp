![Alt text](http://calenderp.appspot.com/images/calenderp.png)

About
-----

CalenDerp is a Facebook app that lets you put all your birthdays and events into Google Calendar. I wrote the application out of frustration when none of the existing apps I tried worked. 

It's a work in progress, there are a lot of things I want to change but it's starting to get there.

It works using a combination of Google's appengine, Google Calendar API, Facebook's Graph API and Python. Once you are authed with both Facebook and Google, CalenDerp queues up all the work in the task queue and syncs your calendars. Once every 30 mins the calendars are refreshed using a cronjob.

Anyway give it a try: <http://apps.facebook.com/calenderp/>

Todo
----
 - Add translations for more languages.
 - Work on the test suite, so far we have a few tests but not many.
 - Work on optimizing things, we're starting to use a lot of our quotas.
 - Update all of the function's documentation strings, as I've refactored the code the documentation strings have started to get a bit out of sync with the actual code.
 - Figure out how to get locale for user before they have installed the Facebook application, that will let us display install.html in their native language.
 - Re-design the user interface.

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
