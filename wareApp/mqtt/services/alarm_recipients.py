"""Who receives alarm e-mails. Edit these lists, then deploy and restart.

* SOFTWARE_TEAM receives the alarms of every site.
* GROUND_TEAM_ALL_SITES: ground-team members who receive every site's alarms.
* GROUND_TEAM maps a site id to the ground-team members for that site only.

Which group gets a given alarm type on a site can be switched off per site and
type with AlarmSetting (email_software / email_ground) in Django admin.
While all lists are empty, ALARM_EMAIL_DEFAULT_TO from warehouse/.env is used.
On test servers ALARM_EMAIL_OVERRIDE_TO still replaces every recipient.

Example of a per-site entry:

    GROUND_TEAM = {
        183: ["farrukhnagar.ground@aviconncorp.com"],
    }
"""

SOFTWARE_TEAM = [
    "ashutosh.dubey@aviconncorp.com",
]

GROUND_TEAM_ALL_SITES = [
    "rakesh.kumar@aviconncorp.com",
]

# site id -> list of e-mail addresses
GROUND_TEAM = {
}
