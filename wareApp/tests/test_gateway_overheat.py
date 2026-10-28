"""POST /api/temp/dispatch/mail/ - gateway overheat alerts (wareApp/gateway_overheat.py)."""

from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from wareApp import gateway_overheat
from wareApp.alarm_feed import active_alarms
from wareApp.models import AlarmNotifications, HomeGatewayId, Site


def body(site_id, temperature=87.34, gateway_no="2"):
    return {
        "Site Id": site_id,
        "Site Name": "Test site",
        "Site Type": "WH-Energy Savings",
        "Gateway No": gateway_no,
        "Gateway Info": {
            "Temperature": temperature,
            "CPU Status": {"cpu0": "1.2 GHz", "cpu1": "1.2 GHz"},
            "Fan PWM": 255,
        },
    }


class GatewayOverheatApiTests(TestCase):
    url = "/api/temp/dispatch/mail/"

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.site = Site.objects.create(site_name="Hot site", site_type=1)
        notify = mock.patch.object(gateway_overheat, "notify")
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def post(self, data):
        return self.client.post(self.url, data, format="json", HTTP_HOST="asem.aviconncorp.com")

    def test_alert_is_stored_and_emailed(self):
        response = self.post(body(self.site.id))
        self.assertEqual((response.status_code, response.data["status"]), (200, "stored"))
        alarm = AlarmNotifications.objects.get()
        self.assertEqual((alarm.Alarm_type, alarm.object_type, alarm.object_id), (13, 5, 2))
        self.assertIn("CPU 87.3 °C", alarm.to_do)
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.args[1], "Gateway Overheat")

    def test_repeats_are_throttled_then_counted_on_one_row(self):
        self.post(body(self.site.id))
        self.assertEqual(self.post(body(self.site.id)).data["status"], "throttled")
        cache.delete(f"gateway-overheat-store:{self.site.id}:2")  # store window passed
        response = self.post(body(self.site.id, temperature=91))
        self.assertEqual(response.data["status"], "repeated")
        alarm = AlarmNotifications.objects.get()
        self.assertEqual(alarm.occurrences, 2)
        self.assertIn("CPU 91.0 °C", alarm.to_do)
        self.notify.assert_called_once()  # e-mail window still closed

    def test_each_gateway_is_its_own_alarm(self):
        self.post(body(self.site.id, gateway_no="1"))
        self.post(body(self.site.id, gateway_no="2"))
        self.assertEqual(AlarmNotifications.objects.count(), 2)
        self.assertEqual(self.notify.call_count, 2)

    def test_bad_requests_get_400(self):
        self.assertEqual(self.post({"Site Id": "x"}).status_code, 400)
        self.assertEqual(self.post({"Site Id": self.site.id}).status_code, 400)
        self.assertEqual(self.post(body(999999)).status_code, 400)
        self.assertFalse(AlarmNotifications.objects.exists())

    @override_settings(ALARM_FEED_MAX_AGE_DAYS=30)
    def test_alarm_feed_shows_gateway_row(self):
        HomeGatewayId.objects.create(connected_to=self.site, hgw_id="avc_test_000001_2")
        self.post(body(self.site.id))
        row = active_alarms([self.site.id])[0]
        self.assertEqual(row["source"], "gateway")
        self.assertEqual(row["alarm"], "Gateway Overheat")
        self.assertEqual(row["home_gateway_id"], "avc_test_000001_2")
        self.assertIsNone(row["leg_id"])
