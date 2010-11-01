![Alt text](http://calenderp.appspot.com/images/calenderp.png)

About
-----

CalenDerp is a Facebook app that lets you put all your birthdays and events into Google Calendar. I wrote the application out of frustration when none of the existing apps I tried worked. 

It's a work in progress, there are a lot of things I want to change but it's starting to get there.

It works using a combination of Google's appengine, Google Calendar API, Facebook's Graph API and Python. Once you are authed with both Facebook and Google, CalenDerp queues up all the work in the task queue and syncs your calendars. Once every 30 mins the calendars are refreshed using a cronjob.

Todo
----
 - Check for Facebook permisions properly, make sure we have the exact ones needed
 - Check for Calendars properly, re-create them if not there.
 - Process requests to the Google Calendar API in batches, hopefully keeping us within quotas.
 - Add status attribute to users and have it being updated and displayed. Give the users a proper idea of what's happening.
 - When we're out of quota display a message to the users, explain the delay.
 - Revoke oAuth token before deleting users.
 - Make status page a lot clearer, explain what's happening better.
 - Re-organise files, prune stuff that's not needed and seperate the templates
   from Python code.

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
