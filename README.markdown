![Alt text](http://calenderp.appspot.com/images/calenderp.png)

About
-----

CalenDerp is a Facebook app that lets you put all your birthdays and events into Google Calendar. I wrote the application out of frustration when none of the existing apps I tried worked. 

It's a work in progress, there are a lot of things I want to change but it's starting to get there.

It works using a combination of Google's appengine, Google Calendar API, Facebook's Graph API and Python. Once you are authed with both Facebook and Google, CalenDerp queues up all the work in the task queue and syncs your calendars. Once every 30 mins the calendars are refreshed using a cronjob.

Anyway give it a try: <http://apps.facebook.com/calenderp/>

Todo
----
 - Process requests to the Google Calendar API in batches, hopefully keeping us within quotas.
 - Add translations for different languages
 - Figure out how to get locale for user before they have installed the Facebook application, that will let us display install.html in their native language.
 - Figure out why some users are constantly shown the install page, what's wrong with the facebook_connect code
 - Make sure the translator function is being set properly everywhere, status updates aren't being translated ATM
 - Investigate Google Calendar timezones, I'm giving it UTC time but apparently that's not being converted their end
 - Only store a hash of event descriptions because they are far too long.

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
