from datetime import datetime

from django.test import TestCase
from unittest.mock import patch
from rest_framework.test import APIRequestFactory

from wareApp.models import DGAlertsData, DGFuelAlertsData, DgUnitConsumption, DgFuelConsumptionData, Site
from wareApp.views import (
    DgFuelConsumptionDataApi_new,
    DgFuelConsumptionDataApiUsingLoconavAPI_new,
    DgFuelConsumptionDataCustomRangeApiUsingPushAPIs,
)


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
        DGAlertsData.objects.create(
            alert_data={
                "alert_type": "theft",
                "timestamp": 1788433200,
                "value": 9.75,
                "vehicle_number": self.site.partner_dg_fuel_id,
            }
        )

    class _FakeValuesQuerySet(list):
        def values(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def exists(self):
            return bool(self)

    def make_json_request(self, path, payload, remote_addr):
        request = APIRequestFactory().post(path, payload, format="json")
        request.META["REMOTE_ADDR"] = remote_addr
        return request

    def test_normalized_alerts_are_returned_by_daily_graph_api(self):
        request = self.make_json_request(
            "/api/dgFuelConsumptionData/",
            {"site_id": self.site.id, "date": "2026/09/03"},
            "10.0.0.1",
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
        self.assertNotIn({"x": 1788433200000, "y": 9.75}, response.data["theft_alert"]["data"])

    def test_legacy_graph_api_also_returns_normalized_alerts(self):
        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": "2026/09/03"},
            "10.0.0.2",
        )

        response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["refuel_alert"]["data"],
            [{"x": 1788422400000, "y": 12.5}],
        )
        self.assertEqual(
            response.data["theft_alert"]["data"],
            [{"x": 1788426000000, "y": 2.25}],
        )

    def test_seconds_based_loconav_alerts_are_normalized_to_milliseconds(self):
        site = Site.objects.create(
            site_name="DG graph seconds test site",
            partner_dg_fuel_id="DCGenerator-01",
            partner_dg_provider="loconav",
        )
        refuel_seconds = int(datetime(2026, 9, 3, 10, 52).timestamp())
        DGFuelAlertsData.objects.create(
            site=site,
            vehicle_number=site.partner_dg_fuel_id,
            alert_name="refuel",
            fuel_consumption=40.82,
            epoch_time=str(refuel_seconds),
            created=self.timestamp,
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionData/",
            {"site_id": site.id, "date": "2026/09/03"},
            "10.0.0.3",
        )

        response = DgFuelConsumptionDataApiUsingLoconavAPI_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["refuel_alert"]["data"],
            [{"x": refuel_seconds * 1000, "y": 40.82}],
        )

    def test_dg_unit_series_is_hidden_when_provider_fuel_is_unavailable(self):
        site = Site.objects.create(
            site_name="DG graph unavailable fuel site",
            partner_dg_fuel_id="DG-UNAVAIL-01",
            partner_dg_provider="roadcast",
        )
        fake_rows = self._FakeValuesQuerySet([
            {
                "epoch_time": "1757030399000",
                "unit_consumption": 3.63,
                "dg_fuel_consumption": None,
                "fetch_fuel_data": True,
                "created": datetime(2026, 9, 4, 23, 59, 59),
                "dg_start_date": datetime(2026, 9, 4, 0, 0),
            }
        ])

        request = self.make_json_request(
            "/api/dgFuelConsumptionData/",
            {"site_id": site.id, "date": "2026/09/04"},
            "10.0.0.4",
        )

        with patch("wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows):
            response = DgFuelConsumptionDataApiUsingLoconavAPI_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dg_unit_data"]["data"], [])
        self.assertEqual(response.data["dg_fuel_data"]["data"], [])
        self.assertEqual(response.data["dg_unit_per_litre_data"]["data"], [])

    def test_dg_unit_graph_is_anchored_to_selected_day_start(self):
        site = Site.objects.create(
            site_name="DG graph day anchor site",
            partner_dg_fuel_id="DG-DAY-01",
            partner_dg_provider="roadcast",
        )
        selected_day_start = int(datetime(2026, 9, 4, 0, 0).timestamp() * 1000)
        fake_rows = self._FakeValuesQuerySet([
            {
                "epoch_time": "1757030399000",
                "unit_consumption": 4.25,
                "dg_fuel_consumption": 2.5,
                "fetch_fuel_data": False,
                "created": datetime(2026, 9, 4, 23, 59, 59),
                "dg_start_date": datetime(2026, 9, 4, 0, 0),
            }
        ])

        request = self.make_json_request(
            "/api/dgFuelConsumptionData/",
            {"site_id": site.id, "date": "2026/09/04"},
            "10.0.0.5",
        )

        with patch("wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows):
            response = DgFuelConsumptionDataApiUsingLoconavAPI_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["dg_unit_data"]["data"],
            [{"x": selected_day_start, "y": 4.25}],
        )
        self.assertEqual(
            response.data["dg_fuel_data"]["data"],
            [{"x": selected_day_start, "y": 2.5}],
        )

    def test_custom_range_hides_dg_series_when_provider_fuel_is_unavailable(self):
        site = Site.objects.create(
            site_name="DG custom range unavailable site",
            partner_dg_fuel_id="DG-CUSTOM-UNAVAIL",
            partner_dg_provider="roadcast",
        )
        fake_rows = self._FakeValuesQuerySet([
            {
                "epoch_time": "1757030399000",
                "unit_consumption": 3.63,
                "dg_fuel_consumption": None,
                "fetch_fuel_data": True,
                "created": datetime(2026, 9, 4, 23, 59, 59),
                "dg_start_date": datetime(2026, 9, 4, 0, 0),
            }
        ])

        request = self.make_json_request(
            "/api/dgFuelConsumptionDataCustomRange/",
            {"site_id": site.id, "from_date": "2026-09-04", "end_date": "2026-09-04"},
            "10.0.0.6",
        )

        with patch("wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows):
            response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dg_unit_data"]["data"], [])
        self.assertEqual(response.data["dg_fuel_data"]["data"], [])
        self.assertEqual(response.data["dg_unit_per_litre_data"]["data"], [])

    def test_custom_range_shows_zero_fuel_without_unit_per_litre(self):
        site = Site.objects.create(
            site_name="DG custom range zero fuel site",
            partner_dg_fuel_id="DG-CUSTOM-ZERO",
            partner_dg_provider="roadcast",
        )
        expected_x = int(datetime(2026, 9, 4, 0, 0).timestamp() * 1000)
        fake_rows = self._FakeValuesQuerySet([
            {
                "epoch_time": "1757030399000",
                "unit_consumption": 3.63,
                "dg_fuel_consumption": 0.0,
                "fetch_fuel_data": False,
                "created": datetime(2026, 9, 4, 23, 59, 59),
                "dg_start_date": datetime(2026, 9, 4, 0, 0),
            }
        ])

        request = self.make_json_request(
            "/api/dgFuelConsumptionDataCustomRange/",
            {"site_id": site.id, "from_date": "2026-09-04", "end_date": "2026-09-04"},
            "10.0.0.7",
        )

        with patch("wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows):
            response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dg_unit_data"]["data"], [{"x": expected_x, "y": 3.63}])
        self.assertEqual(response.data["dg_fuel_data"]["data"], [{"x": expected_x, "y": 0.0}])
        self.assertEqual(response.data["dg_unit_per_litre_data"]["data"], [])

    def test_custom_range_shows_valid_fuel_with_day_start_timestamp(self):
        site = Site.objects.create(
            site_name="DG custom range valid fuel site",
            partner_dg_fuel_id="DG-CUSTOM-VALID",
            partner_dg_provider="roadcast",
        )
        expected_x = int(datetime(2026, 9, 4, 0, 0).timestamp() * 1000)
        fake_rows = self._FakeValuesQuerySet([
            {
                "epoch_time": "1757030399000",
                "unit_consumption": 230.14,
                "dg_fuel_consumption": 76.29,
                "fetch_fuel_data": False,
                "created": datetime(2026, 9, 4, 23, 59, 59),
                "dg_start_date": datetime(2026, 9, 4, 0, 0),
            }
        ])
        DgFuelConsumptionData.objects.create(
            site=site,
            fuel_consumption=50.0,
            epoch_time="1757030400",
            created=datetime(2026, 9, 4, 8, 0),
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionDataCustomRange/",
            {"site_id": site.id, "from_date": "2026-09-04", "end_date": "2026-09-04"},
            "10.0.0.8",
        )

        with patch("wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows):
            response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dg_unit_data"]["data"], [{"x": expected_x, "y": 230.14}])
        self.assertEqual(response.data["dg_fuel_data"]["data"], [{"x": expected_x, "y": 76.29}])
        self.assertEqual(response.data["dg_unit_per_litre_data"]["data"], [{"x": expected_x, "y": round(230.14 / 76.29, 2)}])
        self.assertEqual(response.data["data"], [{"x": 1757030400000, "y": 50.0}])

    def test_custom_range_alert_epochs_are_normalized_to_milliseconds(self):
        site = Site.objects.create(
            site_name="DG custom range alerts site",
            partner_dg_fuel_id="DG-CUSTOM-ALERTS",
            partner_dg_provider="roadcast",
        )
        DGFuelAlertsData.objects.create(
            site=site,
            vehicle_number=site.partner_dg_fuel_id,
            alert_name="refuel",
            fuel_consumption=11.5,
            epoch_time="1757030400",
            created=datetime(2026, 9, 4, 9, 0),
        )
        DGFuelAlertsData.objects.create(
            site=site,
            vehicle_number=site.partner_dg_fuel_id,
            alert_name="theft",
            fuel_consumption=2.75,
            epoch_time="1757034000000",
            created=datetime(2026, 9, 4, 10, 0),
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionDataCustomRange/",
            {"site_id": site.id, "from_date": "2026-09-04", "end_date": "2026-09-04"},
            "10.0.0.9",
        )

        response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["refuel_alert"]["data"], [{"x": 1757030400000, "y": 11.5}])
        self.assertEqual(response.data["theft_alert"]["data"], [{"x": 1757034000000, "y": 2.75}])