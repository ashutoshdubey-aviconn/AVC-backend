from datetime import datetime

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from wareApp.models import DGFuelAlertsData, Site
from wareApp.views import DgFuelConsumptionDataApiUsingLoconavAPI_new


class DgFuelGraphApiTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            site_name="DG graph API test site",
            partner_dg_fuel_id="353691846842382",
            partner_dg_provider="roadcast",
        )
        self.timestamp = datetime(2026, 9, 3, 10, 30)
        DGFuelAlertsData.objects.create(
            site=self.site,
            vehicle_number=self.site.partner_dg_fuel_id,
            alert_name="refuel",
            fuel_consumption=12.5,
            epoch_time="1788422400000",
            created=self.timestamp,
        )
        DGFuelAlertsData.objects.create(
            site=self.site,
            vehicle_number=self.site.partner_dg_fuel_id,
            alert_name="theft",
            fuel_consumption=2.25,
            epoch_time="1788426000000",
            created=self.timestamp,
        )

    def test_normalized_alerts_are_returned_by_daily_graph_api(self):
        request = APIRequestFactory().post(
            "/api/dgFuelConsumptionData/",
            {"site_id": self.site.id, "date": "2026/09/03"},
            format="json",
        )

        response = DgFuelConsumptionDataApiUsingLoconavAPI_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["refuel_alert"]["data"],
            [{"x": 1788422400000, "y": 12.5}],
        )
        self.assertEqual(
            response.data["theft_alert"]["data"],
            [{"x": 1788426000000, "y": 2.25}],
        )