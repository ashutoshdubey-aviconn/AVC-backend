"""Views merged from the colleague's code (54313d5) on 2026-11-21 keep their responses.

See docs/merge/views_merge_decisions_20261121.csv.
"""

from datetime import date, datetime, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from wareApp.models import AisleGroup, DailySiteReading, FansData, LightsData, Site, User


class MergedColleagueViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="merge-admin", password="x", UserType=1)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.site = Site.objects.create(site_name="Merged views", site_type=2, is_live=True,
                                        live_date=datetime(2026, 1, 1))
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="Room A", is_active=True)
        self.aisle.refresh_from_db()

    def test_lights_keys_and_login_required(self):
        LightsData.objects.create(areaName="Dock", totalLights=4, watt_18_Lights=1, watt_20_Lights=1,
                                  watt_24_Lights=1, watt_36_Lights=1, watt_40_Lights=0,
                                  totalWattLights=98, totalUnits=1.5)
        body = self.client.post("/api/lightsDataApi/", {}, format="json").json()
        self.assertEqual(body["status"], 200)
        self.assertEqual(body["data"][0], {"areaName": "Dock", "totalLights": 4, "18Watt": 1, "20Watt": 1,
                                           "24Watt": 1, "36Watt": 1, "40Watt": 0,
                                           "totalWattLights": 98, "totalUnits": 1.5})
        self.assertIn(APIClient().post("/api/lightsDataApi/", {}, format="json").status_code, (401, 403))

    def test_fans_keys(self):
        FansData.objects.create(areaName="Hall", totalFans=3, watt_80_Lights=2, watt_100_Lights=1,
                                totalWattFans=260, totalUnits=2.0)
        body = self.client.post("/api/FansDataApi/", {}, format="json").json()
        self.assertEqual(body["data"][0], {"areaName": "Hall", "totalFans": 3, "80watt": 2, "100watt": 1,
                                           "totalWattFans": 260, "totalUnits": 2.0})

    def test_submetering_bar_chart(self):
        day = date(2026, 3, 2)
        DailySiteReading.objects.create(associated_Site=self.site, aisle_group=self.aisle,
                                        leg_id=str(self.aisle.id), reading_for=day,
                                        unit_consumption=7.256, is_visible=True)
        body = self.client.post("/api/submeteringMonthlyBarChart/", {
            "site_id": self.site.id, "from_date": "2026/03/01", "till_date": "2026/03/03"}, format="json").json()
        self.assertEqual(body["Dates"], ["2026-03-01", "2026-03-02", "2026-03-03"])
        self.assertEqual(body["Data"], [{"name": "Room A", "data": [0.0, 7.26, 0.0], "type": "column"}])

    def test_submetering_snapshot_totals(self):
        yesterday = (datetime.now() - timedelta(days=1)).date()
        leg = self.aisle.attached_leg_id
        DailySiteReading.objects.create(associated_Site=self.site, aisle_group=self.aisle, leg_id=leg,
                                        reading_for=yesterday, unit_consumption=10.0, is_visible=True)
        DailySiteReading.objects.create(associated_Site=self.site, aisle_group=self.aisle, leg_id=leg,
                                        reading_for=date(2026, 2, 1), unit_consumption=5.0, is_visible=True)
        body = self.client.post("/api/submeteringSnapshot/", {"site_id": self.site.id}, format="json").json()
        self.assertEqual(body["status"], 200)
        self.assertEqual(body["energy_consumed"], 15.0)
        self.assertEqual(body["live_date"], "2026-01-01")
        self.assertEqual(set(body), {"status", "alarms", "energy_consumed", "dailyAvg", "monthlyAvg",
                                     "firstmnthDate", "current_date", "live_date"})

    def test_submetering_snapshot_without_live_date(self):
        self.site.live_date = None
        self.site.save()
        body = self.client.post("/api/submeteringSnapshot/", {"site_id": self.site.id}, format="json").json()
        self.assertEqual(body["status"], 200)
        self.assertEqual(body["energy_consumed"], 0.0)
