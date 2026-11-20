"""Hourly chart APIs mark spread (estimated) hours: series[].estimated, one flag per hour."""

from datetime import date, datetime, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from wareApp.models import AisleGroup, DailySiteReading, HourlySiteReading, Site, User

DAY = date(2026, 11, 16)


class HourlyEstimatedFlagTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="Estimated site", site_type=2, is_live=False)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="Aisle A", is_active=True)
        self.aisle.refresh_from_db()
        leg = self.aisle.attached_leg_id
        DailySiteReading.objects.create(associated_Site=self.site, aisle_group=self.aisle, leg_id=leg,
                                        reading_for=DAY, unit_consumption=5.0, is_visible=True)
        for hour in range(5):
            at = datetime.combine(DAY, datetime.min.time()) + timedelta(hours=hour)
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=leg, unit_consumption=1.0,
                reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59), is_visible=True,
                is_estimated=hour in (2, 3),
            )
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))
        self.body = {"site_id": self.site.id, "date": DAY.strftime("%Y/%m/%d")}

    def flags(self, url, key="Data"):
        response = self.client.post(url, self.body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        series = [s for s in response.json()[key] if s["name"] != "baseline"]
        self.assertEqual(len(series), 1)
        return series[0]["estimated"]

    def check(self, flags):
        self.assertEqual(len(flags), 24)
        self.assertEqual([hour for hour, flag in enumerate(flags) if flag], [2, 3])

    def test_hourly_saving_data(self):
        self.check(self.flags("/api/hourlySavingData/"))
        self.check(self.flags("/api/hourlySavingData/", "SavingData"))

    def test_submetering_hourly_data(self):
        self.check(self.flags("/api/submeteringHourlyData/"))

    def test_site_hourly_consumption_data(self):
        self.check(self.flags("/api/getSiteHourlyConsumptionData/"))
