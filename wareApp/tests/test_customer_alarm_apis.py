"""Customer / site page alarm APIs read the open alarms (fixed 2026-11-06).

They used to read user_level=4 rows with created_by = the customer; the alarm
code writes user_level=2 rows without created_by, so they were always empty.
"""

from datetime import datetime

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from wareApp.models import AisleGroup, AlarmNotifications, Site, User


class CustomerAlarmApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = User.objects.create(username="Purplle", UserType=4)
        self.site = Site.objects.create(
            site_name="Purplle GGN", site_type=2, customer=self.customer, is_live=True,
            live_date=datetime(2026, 9, 1), baseline_date=datetime(2026, 9, 1),
        )
        self.other = Site.objects.create(
            site_name="Purplle HDR", site_type=2, customer=self.customer, is_live=True,
            live_date=datetime(2026, 9, 1), baseline_date=datetime(2026, 9, 1),
        )
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="HDR-GF")
        stranger = User.objects.create(username="Other", UserType=4)
        elsewhere = Site.objects.create(site_name="Not theirs", site_type=2, customer=stranger)

        def alarm(site, alarm_type, active=True, **extra):
            AlarmNotifications.objects.create(
                site_id=site, Alarm_type=alarm_type, Alarm_priority=0, user_level=2, is_active=active,
                created_time=datetime(2026, 11, 6, 12, 2), **extra,
            )

        alarm(self.site, 15, object_type=5, object_id=1)  # Gateway Disconnected
        alarm(self.site, 11, aisle_group=self.aisle, object_type=4)  # Bypassed
        alarm(self.site, 11, active=False, aisle_group=self.aisle)  # closed: not counted
        alarm(self.other, 15, object_type=5, object_id=1)
        alarm(elsewhere, 15)  # another customer's site
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))

    def post(self, url, body):
        response = self.client.post(url, body, format="json")
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_customer_page_table(self):
        body = self.post("/api/alarmListOnCustomerPage/", {"id": self.customer.id})
        rows = {row["site_id"]: row for row in body["data"]}
        self.assertEqual(set(rows), {self.site.id, self.other.id})
        self.assertEqual(rows[self.site.id]["alarms"], {"Bypassed": 1, "Gateway Disconnected": 1})
        self.assertEqual(rows[self.site.id]["total_alarm_count"], 2)
        self.assertEqual(rows[self.site.id]["site_type"], "WH_Energy_Saving")
        self.assertEqual(set(rows[self.site.id]), {"site_id", "site_name", "alarms", "total_alarm_count", "site_type"})

    def test_customer_page_graph(self):
        body = self.post("/api/getCustAlarmGraph/", {"id": self.customer.id})
        self.assertEqual(body["alarm_name_list"], ["Bypassed", "Gateway Disconnected"])
        self.assertEqual(body["Data"], [
            {"name": "Bypassed", "data": [1], "type": "column"},
            {"name": "Gateway Disconnected", "data": [2], "type": "column"},
        ])

    def test_site_page_table(self):
        body = self.post("/api/alarmListOnSitePage/", {"site_id": self.site.id})
        self.assertEqual(len(body["data"]), 2)  # the closed Bypassed is left out
        names = {row["alarm_type"]: row for row in body["data"]}
        self.assertEqual(names["Bypassed"]["object_name"], "HDR-GF")
        self.assertEqual(names["Gateway Disconnected"]["object_name"], 1)
        self.assertEqual(names["Gateway Disconnected"]["alarm_priority"], "High")
        self.assertEqual(names["Gateway Disconnected"]["created_date"], "06-11-2026")
        self.assertEqual(set(body["data"][0]), {"alarm_type", "object_type", "object_name", "alarm_priority", "created_date"})

    def test_customer_snapshot_alarm_count(self):
        body = self.post("/api/customerSnapShotEnergySavingApi/", {"id": self.customer.id, "user_type": 4})
        self.assertEqual(body["alarms"], 3)  # 2 + 1 open on the customer's two sites

    def test_empty_when_no_open_alarms(self):
        AlarmNotifications.objects.update(is_active=False)
        self.assertEqual(self.post("/api/alarmListOnCustomerPage/", {"id": self.customer.id})["data"], [])
        self.assertEqual(self.post("/api/getCustAlarmGraph/", {"id": self.customer.id})["Data"], [])
        self.assertEqual(self.post("/api/alarmListOnSitePage/", {"site_id": self.site.id})["data"], [])
