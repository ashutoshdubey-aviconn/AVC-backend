"""Who receives alarm e-mails. Edit these lists, then deploy and restart.

* SOFTWARE_TEAM receives the alarms of every site.
* GROUND_TEAM maps a site id to the people who receive that site's alarms.

Which group gets a given alarm type on a site can be switched off per site and
type with AlarmSetting (email_software / email_ground) in Django admin.
While both lists are empty, ALARM_EMAIL_DEFAULT_TO from warehouse/.env is used.
On test servers ALARM_EMAIL_OVERRIDE_TO still replaces every recipient.

Example:

    SOFTWARE_TEAM = [
        "dev1@aviconncorp.com",
        "dev2@aviconncorp.com",
    ]

    GROUND_TEAM = {
        183: ["farrukhnagar.ground@aviconncorp.com"],
        185: ["farrukhnagar.ground@aviconncorp.com"],
    }
"""

SOFTWARE_TEAM = [
]

# site id -> list of e-mail addresses
GROUND_TEAM = {
}
