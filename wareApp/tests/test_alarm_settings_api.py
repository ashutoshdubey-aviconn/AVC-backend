"""alarmSettings/: Auto / Manual / Off per site and alarm type (Super_Admin only)."""

from django.test import TestCase
from rest_framework.test import APIClient

from wareApp.models import AlarmNotifications, AlarmSetting, Site, User
from wareApp.mqtt.services import alarm_policy

URL = "/api/alarmSettings/"


class AlarmSettingsApiTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="Settings site", site_type=2, is_live=True)
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))

    def rows(self, body):
        return {row["alarm_type"]: row for row in body["data"]}

    def test_get_lists_every_type_with_defaults(self):
        body = self.client.get(URL, {"site_id": self.site.id}).json()
        rows = self.rows(body)
        self.assertEqual(len(rows), len(AlarmNotifications.alarm_type))
        high = rows[AlarmNotifications.HIGH_CONSUMPTION]
        self.assertEqual((high["mode"], high["unit"], high["group"]), ("default", "kWh / day", "Consumption"))
        self.assertFalse(rows[AlarmNotifications.DG_OVERTIME]["raised"])
        self.assertIsNone(rows[AlarmNotifications.CONSUMPTION_SPIKE]["unit"])

    def test_manual_off_and_back_to_default(self):
        body = self.client.post(URL, {"site_id": self.site.id, "alarm_type": 7, "mode": "manual",
                                      "threshold": 250, "email_ground": False}, format="json").json()
        high = self.rows(body)[7]
        self.assertEqual((high["mode"], high["threshold"], high["email_ground"], high["email_software"]),
                         ("manual", 250.0, False, True))
        self.assertEqual(alarm_policy.manual_threshold(self.site.id, 7), 250.0)

        self.client.post(URL, {"site_id": self.site.id, "alarm_type": 7, "mode": "off"}, format="json")
        setting = AlarmSetting.objects.get(site=self.site, alarm_type=7)
        self.assertEqual((setting.mode, setting.threshold, setting.email_ground), (AlarmSetting.OFF, None, False))
        self.assertTrue(alarm_policy.is_off(self.site.id, 7))

        body = self.client.post(URL, {"site_id": self.site.id, "alarm_type": 7, "mode": "default"},
                                format="json").json()
        self.assertEqual(self.rows(body)[7]["mode"], "default")
        self.assertFalse(AlarmSetting.objects.filter(site=self.site).exists())

    def test_invalid_requests(self):
        cases = [
            {"site_id": 999999, "alarm_type": 7, "mode": "auto"},
            {"site_id": self.site.id, "alarm_type": 99, "mode": "auto"},
            {"site_id": self.site.id, "alarm_type": 7, "mode": "sometimes"},
            {"site_id": self.site.id, "alarm_type": 7, "mode": "manual"},
            {"site_id": self.site.id, "alarm_type": 7, "mode": "manual", "threshold": "abc"},
            {"site_id": self.site.id, "alarm_type": 17, "mode": "manual", "threshold": 5},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(self.client.post(URL, case, format="json").status_code, 400)
        self.assertFalse(AlarmSetting.objects.exists())

    def test_only_super_admin(self):
        other = APIClient()
        other.force_authenticate(User.objects.create(username="customer", UserType=4))
        self.assertEqual(other.get(URL, {"site_id": self.site.id}).status_code, 403)
        self.assertEqual(other.post(URL, {"site_id": self.site.id, "alarm_type": 7, "mode": "off"},
                                    format="json").status_code, 403)
        self.assertEqual(APIClient().get(URL, {"site_id": self.site.id}).status_code, 401)
