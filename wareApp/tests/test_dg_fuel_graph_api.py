from datetime import datetime, timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch
from rest_framework.test import APIClient, APIRequestFactory

from wareApp.models import (
    AisleGroup,
    DGAlertsData,
    DGFuelAlertsData,
    DgUnitConsumption,
    DgFuelConsumptionData,
    Site,
)
from wareApp.views import (
    DgFuelConsumptionDataApi_new,
    DgFuelConsumptionDataApiUsingLoconavAPI_new,
    DgFuelConsumptionDataCustomRangeApiUsingPushAPIs,
)


class DgFuelGraphApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = Site.objects.create(
            site_name="DG graph API test site",
            partner_dg_fuel_id="353691846842382",
            partner_dg_provider="roadcast",
        )
        self.timestamp = datetime(2026, 9, 3, 10, 30)
        DGAlertsData.objects.create(
            alert_data={
                "alert_type": "RefuelingAlert",
                "timestamp": 1788422400,
                "refueled_in_liters": 12.5,
                "vehicle_number": self.site.partner_dg_fuel_id,
            },
            created=self.timestamp,
        )
        DGAlertsData.objects.create(
            alert_data={
                "alert_type": "theft",
                "timestamp": 1788426000,
                "value": 2.25,
                "vehicle_number": self.site.partner_dg_fuel_id,
            },
            created=self.timestamp,
        )

    def make_fuel_row(self, created, fuel_consumption):
        epoch_ms = int(created.timestamp() * 1000)
        return DgFuelConsumptionData.objects.create(
            site=self.site,
            vehicle_number=self.site.partner_dg_fuel_id,
            fuel_consumption=fuel_consumption,
            epoch_time=str(epoch_ms),
            created=created,
        )

    def make_unit_row(
        self, site, aisle_group, created, unit_consumption, fuel_consumption
    ):
        return DgUnitConsumption.objects.create(
            site=site,
            aisle_group=aisle_group,
            unit_consumption=unit_consumption,
            dg_fuel_consumption=fuel_consumption,
            dg_start_date=created - timedelta(hours=1),
            dg_end_date=created,
            created=created,
            epoch_time=str(int(created.timestamp() * 1000)),
            fetch_fuel_data=False,
            is_dg_on=False,
        )

    def make_alert_row(self, site, alert_name, created, fuel_consumption):
        return DGFuelAlertsData.objects.create(
            site=site,
            vehicle_number=site.partner_dg_fuel_id,
            alert_name=alert_name,
            fuel_consumption=fuel_consumption,
            epoch_time=str(int(created.timestamp() * 1000)),
            created=created,
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

    def api_post(self, path, payload):
        return self.client.post(path, payload, format="json")

    def test_normalized_alerts_are_returned_by_daily_graph_api(self):
        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ):
            response = self.api_post(
                "/api/dgFuelConsumptionData/",
                {"site_id": self.site.id, "date": "2026/09/03"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider_status"], "OK")
        self.assertEqual(
            response.data["refuel_alert"]["data"],
            [{"x": 1788422400000, "y": 12.5}],
        )
        self.assertEqual(
            response.data["theft_alert"]["data"],
            [{"x": 1788426000000, "y": 2.25}],
        )
        self.assertNotIn(
            {"x": 1788433200000, "y": 9.75}, response.data["theft_alert"]["data"]
        )

    def test_legacy_graph_api_also_returns_normalized_alerts(self):
        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": "2026/09/03"},
            "10.0.0.2",
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ):
            response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider_status"], "OK")
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
        DGAlertsData.objects.create(
            alert_data={
                "alert_type": "deviceFuelFill",
                "timestamp": refuel_seconds,
                "refueled_in_liters": 40.82,
                "vehicle_number": site.partner_dg_fuel_id,
            },
            created=self.timestamp,
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._loconav_subscription_expired",
            return_value=False,
        ):
            response = self.api_post(
                "/api/dgFuelConsumptionData/",
                {"site_id": site.id, "date": "2026/09/03"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider_status"], "OK")
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
        fake_rows = self._FakeValuesQuerySet(
            [
                {
                    "epoch_time": "1757030399000",
                    "unit_consumption": 3.63,
                    "dg_fuel_consumption": None,
                    "fetch_fuel_data": True,
                    "created": datetime(2026, 9, 4, 23, 59, 59),
                    "dg_start_date": datetime(2026, 9, 4, 0, 0),
                }
            ]
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionData/",
            {"site_id": site.id, "date": "2026/09/04"},
            "10.0.0.4",
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ), patch(
            "wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows
        ):
            response = DgFuelConsumptionDataApiUsingLoconavAPI_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dg_unit_data"]["data"], [])
        self.assertEqual(response.data["dg_fuel_data"]["data"], [])
        self.assertEqual(response.data["dg_unit_per_litre_data"]["data"], [])

    def test_roadcast_expired_returns_empty_graph_response(self):
        site = Site.objects.create(
            site_name="124",
            partner_dg_fuel_id="353691846842382",
            partner_dg_provider="roadcast",
        )
        aisle = AisleGroup.objects.create(
            site=site, aisleGroupName="DG Roadcast Expired", power_source=1
        )
        self.make_unit_row(site, aisle, datetime(2026, 9, 4, 23, 59, 59), 3.63, 2.5)

        with patch("wareApp.views.fetch_roadcast_pull_api") as mock_pull_api:
            mock_pull_api.return_value = {
                "data": [],
                "error": [
                    {
                        "error": "Subscription expired",
                        "message": "The device with ID 322105 and name '124' has an expired subscription",
                    }
                ],
                "status": "success",
            }
            response = self.api_post(
                "/api/dgFuelConsumptionData/",
                {"site_id": site.id, "date": "2026/09/04"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider_status"], "SUBSCRIPTION_EXPIRED")
        self.assertEqual(response.data["message"], "DG fuel subscription expired")
        self.assertEqual(response.data["fuel_level"]["data"], [])
        self.assertEqual(response.data["data"], [])
        self.assertEqual(response.data["refuel_alert"]["data"], [])
        self.assertEqual(response.data["theft_alert"]["data"], [])
        self.assertEqual(response.data["dg_unit_data"]["data"], [])
        self.assertEqual(response.data["dg_fuel_consumed"]["data"], [])
        self.assertEqual(response.data["dg_unit_per_litre"]["data"], [])

    def test_zero_unit_rows_are_not_mapped_in_graph_series(self):
        site = Site.objects.create(
            site_name="DG graph zero unit site",
            partner_dg_fuel_id="DG-ZERO-01",
            partner_dg_provider="roadcast",
        )
        fake_rows = self._FakeValuesQuerySet(
            [
                {
                    "epoch_time": "1757030399000",
                    "unit_consumption": 0.0,
                    "dg_fuel_consumption": 2.5,
                    "fetch_fuel_data": False,
                    "created": datetime(2026, 9, 4, 23, 59, 59),
                    "dg_start_date": datetime(2026, 9, 4, 0, 0),
                }
            ]
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionData/",
            {"site_id": site.id, "date": "2026/09/04"},
            "10.0.0.10",
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ), patch(
            "wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows
        ):
            response = DgFuelConsumptionDataApiUsingLoconavAPI_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dg_unit_data"]["data"], [])
        self.assertEqual(response.data["dg_fuel_data"]["data"], [])
        self.assertEqual(response.data["dg_unit_per_litre_data"]["data"], [])

    def test_loconav_expired_returns_empty_graph_response(self):
        site = Site.objects.create(
            site_name="35",
            partner_dg_fuel_id="DG-LOCONAV-EXP",
            partner_dg_provider="loconav",
        )
        aisle = AisleGroup.objects.create(
            site=site, aisleGroupName="DG Loconav Expired", power_source=1
        )
        self.make_unit_row(
            site,
            aisle,
            datetime(2026, 9, 4, 23, 59, 59),
            4.25,
            2.5,
        )

        with patch(
            "wareApp.views.fetch_loconav_report",
            return_value={"message": "Subscription expired for this vehicle"},
        ):
            response = self.api_post(
                "/api/dgFuelConsumptionData/",
                {"site_id": site.id, "date": "2026/09/04"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider_status"], "SUBSCRIPTION_EXPIRED")
        self.assertEqual(response.data["message"], "DG fuel subscription expired")
        self.assertEqual(response.data["fuel_level"]["data"], [])
        self.assertEqual(response.data["data"], [])
        self.assertEqual(response.data["refuel_alert"]["data"], [])
        self.assertEqual(response.data["theft_alert"]["data"], [])
        self.assertEqual(response.data["dg_unit_data"]["data"], [])
        self.assertEqual(response.data["dg_fuel_consumed"]["data"], [])
        self.assertEqual(response.data["dg_unit_per_litre"]["data"], [])

    def test_loconav_offline_payload_is_not_marked_expired(self):
        site = Site.objects.create(
            site_name="DG graph loconav offline site",
            partner_dg_fuel_id="DG-LOCONAV-OFF",
            partner_dg_provider="loconav",
        )
        aisle = AisleGroup.objects.create(
            site=site, aisleGroupName="DG Loconav Offline", power_source=1
        )
        created = datetime(2026, 9, 4, 23, 59, 59)
        self.make_unit_row(site, aisle, created, 4.25, 2.5)
        DgFuelConsumptionData.objects.create(
            site=site,
            vehicle_number=site.partner_dg_fuel_id,
            fuel_consumption=37.75,
            epoch_time=str(int((created - timedelta(hours=2)).timestamp() * 1000)),
            created=created - timedelta(hours=2),
        )

        with patch(
            "wareApp.views.fetch_loconav_report",
            return_value={"status": "offline", "message": "vehicle unavailable"},
        ):
            response = self.api_post(
                "/api/dgFuelConsumptionData/",
                {"site_id": site.id, "date": "2026/09/04"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider_status"], "OK")
        self.assertNotEqual(response.data["data"], [])
        self.assertEqual(response.data["dg_unit_data"]["data"][0]["y"], 4.25)
        self.assertEqual(response.data["dg_fuel_consumed"]["data"][0]["y"], 2.5)

    def test_dg_unit_graph_is_anchored_to_selected_day_start(self):
        site = Site.objects.create(
            site_name="DG graph day anchor site",
            partner_dg_fuel_id="DG-DAY-01",
            partner_dg_provider="roadcast",
        )
        selected_day_start = int(datetime(2026, 9, 4, 0, 0).timestamp() * 1000)
        fake_rows = self._FakeValuesQuerySet(
            [
                {
                    "epoch_time": "1757030399000",
                    "unit_consumption": 4.25,
                    "dg_fuel_consumption": 2.5,
                    "fetch_fuel_data": False,
                    "created": datetime(2026, 9, 4, 23, 59, 59),
                    "dg_start_date": datetime(2026, 9, 4, 0, 0),
                }
            ]
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionData/",
            {"site_id": site.id, "date": "2026/09/04"},
            "10.0.0.5",
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ), patch(
            "wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows
        ):
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
        self.assertEqual(response.data["provider_status"], "OK")

    def test_custom_range_hides_dg_series_when_provider_fuel_is_unavailable(self):
        site = Site.objects.create(
            site_name="DG custom range unavailable site",
            partner_dg_fuel_id="DG-CUSTOM-UNAVAIL",
            partner_dg_provider="roadcast",
        )
        fake_rows = self._FakeValuesQuerySet(
            [
                {
                    "epoch_time": "1757030399000",
                    "unit_consumption": 3.63,
                    "dg_fuel_consumption": None,
                    "fetch_fuel_data": True,
                    "created": datetime(2026, 9, 4, 23, 59, 59),
                    "dg_start_date": datetime(2026, 9, 4, 0, 0),
                }
            ]
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionDataCustomRange/",
            {"site_id": site.id, "from_date": "2026-09-04", "end_date": "2026-09-04"},
            "10.0.0.6",
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ), patch(
            "wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows
        ):
            response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(
                request
            )

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
        fake_rows = self._FakeValuesQuerySet(
            [
                {
                    "epoch_time": "1757030399000",
                    "unit_consumption": 3.63,
                    "dg_fuel_consumption": 0.0,
                    "fetch_fuel_data": False,
                    "created": datetime(2026, 9, 4, 23, 59, 59),
                    "dg_start_date": datetime(2026, 9, 4, 0, 0),
                }
            ]
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionDataCustomRange/",
            {"site_id": site.id, "from_date": "2026-09-04", "end_date": "2026-09-04"},
            "10.0.0.7",
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ), patch(
            "wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows
        ):
            response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(
                request
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["dg_unit_data"]["data"], [{"x": expected_x, "y": 3.63}]
        )
        self.assertEqual(
            response.data["dg_fuel_data"]["data"], [{"x": expected_x, "y": 0.0}]
        )
        self.assertEqual(response.data["dg_unit_per_litre_data"]["data"], [])

    def test_custom_range_shows_valid_fuel_with_day_start_timestamp(self):
        site = Site.objects.create(
            site_name="DG custom range valid fuel site",
            partner_dg_fuel_id="DG-CUSTOM-VALID",
            partner_dg_provider="roadcast",
        )
        expected_x = int(datetime(2026, 9, 4, 0, 0).timestamp() * 1000)
        fake_rows = self._FakeValuesQuerySet(
            [
                {
                    "epoch_time": "1757030399000",
                    "unit_consumption": 230.14,
                    "dg_fuel_consumption": 76.29,
                    "fetch_fuel_data": False,
                    "created": datetime(2026, 9, 4, 23, 59, 59),
                    "dg_start_date": datetime(2026, 9, 4, 0, 0),
                }
            ]
        )
        fuel_rows = self._FakeValuesQuerySet(
            [
                SimpleNamespace(
                    epoch_time="1757030400",
                    fuel_consumption=50.0,
                    created=datetime(2026, 9, 4, 8, 0),
                )
            ]
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionDataCustomRange/",
            {"site_id": site.id, "from_date": "2026-09-04", "end_date": "2026-09-04"},
            "10.0.0.8",
        )

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ), patch(
            "wareApp.views.DgUnitConsumption.objects.filter", return_value=fake_rows
        ), patch(
            "wareApp.views.DgFuelConsumptionData.objects.filter", return_value=fuel_rows
        ):
            response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(
                request
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["dg_unit_data"]["data"], [{"x": expected_x, "y": 230.14}]
        )
        self.assertEqual(
            response.data["dg_fuel_data"]["data"], [{"x": expected_x, "y": 76.29}]
        )
        self.assertEqual(
            response.data["dg_unit_per_litre_data"]["data"],
            [{"x": expected_x, "y": round(230.14 / 76.29, 2)}],
        )
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

        with patch(
            "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
            return_value=False,
        ):
            response = DgFuelConsumptionDataCustomRangeApiUsingPushAPIs.as_view()(
                request
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["refuel_alert"]["data"], [{"x": 1757030400000, "y": 11.5}]
        )
        self.assertEqual(
            response.data["theft_alert"]["data"], [{"x": 1757034000000, "y": 2.75}]
        )

    @patch(
        "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
        return_value=False,
    )
    def test_historical_day_with_data_adds_boundary_points(self, mock_expired):
        selected_day = datetime(2026, 9, 4)
        points = [
            (datetime(2026, 9, 4, 9, 0), 38.5),
            (datetime(2026, 9, 4, 10, 0), 38.2),
            (datetime(2026, 9, 4, 16, 0), 37.9),
        ]
        for created, fuel in points:
            self.make_fuel_row(created, fuel)

        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": "2026/09/04"},
            "10.0.0.11",
        )

        response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        fuel_points = response.data["data"]
        self.assertEqual(
            fuel_points,
            [
                {"x": int(datetime(2026, 9, 4, 0, 0).timestamp() * 1000), "y": 38.5},
                {"x": int(datetime(2026, 9, 4, 9, 0).timestamp() * 1000), "y": 38.5},
                {"x": int(datetime(2026, 9, 4, 10, 0).timestamp() * 1000), "y": 38.2},
                {"x": int(datetime(2026, 9, 4, 16, 0).timestamp() * 1000), "y": 37.9},
                {
                    "x": int(datetime(2026, 9, 4, 23, 59, 59).timestamp() * 1000),
                    "y": 37.9,
                },
            ],
        )

    @patch(
        "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
        return_value=False,
    )
    def test_historical_day_without_data_uses_previous_value(self, mock_expired):
        previous_day = datetime(2026, 9, 14, 16, 0)
        self.make_fuel_row(previous_day, 41.06)

        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": "2026/09/15"},
            "10.0.0.12",
        )

        response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"],
            [
                {"x": int(datetime(2026, 9, 15, 0, 0).timestamp() * 1000), "y": 41.06},
                {
                    "x": int(datetime(2026, 9, 15, 23, 59, 59).timestamp() * 1000),
                    "y": 41.06,
                },
            ],
        )

    @patch(
        "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
        return_value=False,
    )
    def test_historical_day_without_data_and_no_previous_returns_empty(
        self, mock_expired
    ):
        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": "2026/09/15"},
            "10.0.0.13",
        )

        response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], [])

    @patch(
        "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
        return_value=False,
    )
    def test_current_day_with_data_adds_start_boundary_only(self, mock_expired):
        today = timezone.now().date()
        self.make_fuel_row(
            datetime.combine(today, datetime.min.time()) + timedelta(hours=9), 38.5
        )
        self.make_fuel_row(
            datetime.combine(today, datetime.min.time()) + timedelta(hours=10), 38.2
        )
        self.make_fuel_row(
            datetime.combine(today, datetime.min.time()) + timedelta(hours=16), 37.9
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": today.strftime("%Y/%m/%d")},
            "10.0.0.14",
        )

        response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        fuel_points = response.data["data"]
        self.assertEqual(
            fuel_points[0]["x"],
            int(datetime.combine(today, datetime.min.time()).timestamp() * 1000),
        )
        self.assertEqual(fuel_points[0]["y"], 38.5)
        self.assertNotIn(
            {
                "x": int(
                    datetime.combine(
                        today, datetime.max.replace(microsecond=0)
                    ).timestamp()
                    * 1000
                ),
                "y": 37.9,
            },
            fuel_points,
        )

    @patch(
        "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
        return_value=False,
    )
    def test_current_day_without_data_uses_previous_and_now(self, mock_expired):
        today = timezone.now().date()
        previous_day = today - timedelta(days=1)
        self.make_fuel_row(
            datetime.combine(previous_day, datetime.min.time()) + timedelta(hours=16),
            41.06,
        )

        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": today.strftime("%Y/%m/%d")},
            "10.0.0.15",
        )

        before = timezone.now()
        response = DgFuelConsumptionDataApi_new.as_view()(request)
        after = timezone.now()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 2)
        self.assertEqual(response.data["data"][0]["y"], 41.06)
        self.assertEqual(response.data["data"][1]["y"], 41.06)
        self.assertGreater(response.data["data"][1]["x"], response.data["data"][0]["x"])
        self.assertGreaterEqual(
            response.data["data"][1]["x"], int(before.timestamp() * 1000) - 1000
        )
        self.assertLessEqual(
            response.data["data"][1]["x"], int(after.timestamp() * 1000) + 5000
        )

    @patch(
        "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
        return_value=False,
    )
    def test_current_day_without_data_and_no_previous_returns_empty(self, mock_expired):
        today = timezone.now().date()
        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": today.strftime("%Y/%m/%d")},
            "10.0.0.16",
        )

        response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], [])

    @patch(
        "wareApp.views.DgFuelConsumptionDataApi_new._roadcast_subscription_expired",
        return_value=True,
    )
    def test_expired_device_returns_empty_series(self, mock_expired):
        previous_day = datetime(2026, 9, 14, 16, 0)
        self.make_fuel_row(previous_day, 41.06)

        request = self.make_json_request(
            "/api/dgFuelConsumptionData_test/",
            {"site_id": self.site.id, "date": "2026/09/15"},
            "10.0.0.17",
        )

        response = DgFuelConsumptionDataApi_new.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], [])
