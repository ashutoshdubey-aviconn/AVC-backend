"""Who receives alarm e-mails. Edit these lists, then deploy and restart.

* SOFTWARE_TEAM receives the alarms of every site.
* GROUND_TEAM_ALL_SITES: ground-team members who receive every site's alarms.
* LOCATION_TEAMS: ground team per location. A site belongs to the first
  location whose keywords appear in its Site.location or site name
  (case-insensitive). Check the result with:
      python manage.py alarm_recipients
* GROUND_TEAM maps a site id to extra ground-team members for that site only.

Which group gets a given alarm type on a site can be switched off per site and
type with AlarmSetting (email_software / email_ground) in Django admin.
While all lists are empty, ALARM_EMAIL_DEFAULT_TO from warehouse/.env is used.
On test servers ALARM_EMAIL_OVERRIDE_TO still replaces every recipient.
"""

SOFTWARE_TEAM = [
    "ashutosh.dubey@aviconncorp.com",
]

GROUND_TEAM_ALL_SITES = [
    "rakesh.kumar@aviconncorp.com",
]

# location name -> keywords found in the site's location / name, and its team
LOCATION_TEAMS = {
    "Gurgaon": {
        "match": [
            "gurgaon", "gurugram", "gurugaram", "ggn", "binola", "lohari", "luhari",
            "farukhnagar", "farrukhnagar", "hasanpur", "bilaspur", "suncity", "sector-49",
        ],
        "emails": [],
    },
    "Delhi": {
        "match": ["delhi", "okhla", "kapashera", "neb sarai"],
        "emails": [],
    },
    "Mumbai / Bhiwandi": {
        "match": ["bhiwandi", "mumbai"],
        "emails": [],
    },
    "Pune": {"match": ["pune"], "emails": []},
    "Bangalore": {"match": ["bangalore", "bengaluru", "bglr"], "emails": []},
    "Kolkata": {"match": ["kolkata", "dankuni"], "emails": []},
    "Lucknow": {"match": ["lucknow"], "emails": []},
}

# site id -> list of e-mail addresses (extra, for that site only)
GROUND_TEAM = {
}
