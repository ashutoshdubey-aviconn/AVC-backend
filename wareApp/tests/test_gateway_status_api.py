"""gateway-status/: health = online / offline / modbus_issue from the open gateway alarms."""

from datetime import datetime

from django.test import TestCase
from rest_framework.test import APIClient

from wareApp.models import AlarmNotifications, HomeGatewayId, HomeGatewayStatus, Site, User


class GatewayStatusHealthTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="Health site", site_type=1, is_live=True)
        self.merged = Site.objects.create(site_name="Merged site", site_type=1, is_live=True)

    def gateway(self, hgw_id, status):
        hgw = HomeGatewayId.objects.create(hgw_id=hgw_id, connected_to=self.site)
        return HomeGatewayStatus.objects.create(home_gateway=hgw, status=status)

    def alarm(self, hgw_id, alarm_type, site=None, active=True):
        return AlarmNotifications.objects.create(
            site_id=site or self.site, Alarm_type=alarm_type, object_type=5,
            object_id=int(hgw_id.rsplit("_", 1)[-1]), is_active=active,
            created_time=datetime(2026, 11, 20, 9, 0), to_do=f"Gateway {hgw_id}: no data for 3.0 h",
        )

    def health(self):
        client = APIClient()
        client.force_authenticate(User.objects.get_or_create(username="admin", UserType=1)[0])
        body = client.get("/api/gateway-status/?limit=500").json()
        return {row["gateway_id"]: row for row in body["results"]}

    def test_health_from_status_and_open_alarms(self):
        self.gateway("avc_on_000001_1", True)
        self.gateway("avc_off_000001_2", False)
        self.gateway("avc_modbus_000001_3", False)
        self.gateway("avc_down_000001_4", False)
        self.gateway("avc_closed_000001_5", True)
        self.alarm("avc_modbus_000001_3", AlarmNotifications.GATEWAY_SERVICE_ISSUE, site=self.merged)
        self.alarm("avc_down_000001_4", AlarmNotifications.GATEWAY_DISCONNECTED)
        self.alarm("avc_closed_000001_5", AlarmNotifications.GATEWAY_SERVICE_ISSUE, active=False)

        rows = self.health()
        self.assertEqual(
            {gw: row["health"] for gw, row in rows.items()},
            {
                "avc_on_000001_1": "online",
                "avc_off_000001_2": "offline",
                "avc_modbus_000001_3": "modbus_issue",
                "avc_down_000001_4": "offline",
                "avc_closed_000001_5": "online",
            },
        )
        modbus = rows["avc_modbus_000001_3"]
        self.assertFalse(modbus["status"])  # unchanged field
        self.assertTrue(modbus["health_since"].startswith("2026-11-20T09:00"))
        self.assertIn("no data", modbus["health_detail"])
        self.assertIsNone(rows["avc_on_000001_1"]["health_since"])

    def test_disconnected_wins_over_modbus(self):
        self.gateway("avc_both_000001_6", False)
        self.alarm("avc_both_000001_6", AlarmNotifications.GATEWAY_SERVICE_ISSUE)
        self.alarm("avc_both_000001_6", AlarmNotifications.GATEWAY_DISCONNECTED)
        self.assertEqual(self.health()["avc_both_000001_6"]["health"], "offline")

    def test_only_super_admin_can_list(self):
        self.gateway("avc_on_000001_1", True)
        self.assertEqual(APIClient().get("/api/gateway-status/").status_code, 401)
        customer = APIClient()
        customer.force_authenticate(User.objects.create(username="customer", UserType=4))
        self.assertEqual(customer.get("/api/gateway-status/").status_code, 403)
