import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

from wareApp import fuel_providers as fp


class MockResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


class FuelProvidersTests(unittest.TestCase):
    def test_roadcast_primary_success(self):
        start = datetime.utcnow() - timedelta(hours=1)
        end = datetime.utcnow()

        with patch("wareApp.fuel_providers.requests.get") as mock_get:
            mock_get.return_value = MockResponse(200, {"fuel_consumed": 12.5})
            val = fp.fetch_roadcast_fuel("12345", start, end)
            self.assertEqual(val, 12.5)

    def test_roadcast_mapping_fallback(self):
        start = datetime.utcnow() - timedelta(hours=1)
        end = datetime.utcnow()

        # sequence: primary (500) -> map (200 with mapping) -> primary mapped (200 with fuel)
        def side_effect(url, params=None, headers=None, timeout=None):
            if (
                "pull_fuel_report" in url
                and params
                and params.get("device_imei") == "orig"
            ):
                return MockResponse(500, {"error": "server"})
            if "pull_api" in url:
                return MockResponse(
                    200, {"data": [{"deviceImei": "mapped", "deviceId": "orig"}]}
                )
            if (
                "pull_fuel_report" in url
                and params
                and params.get("device_imei") == "mapped"
            ):
                return MockResponse(200, {"fuel_consumed": 42})
            return MockResponse(404, {})

        with patch("wareApp.fuel_providers.requests.get", side_effect=side_effect):
            val = fp.fetch_roadcast_fuel("orig", start, end)
            self.assertEqual(val, 42)

    def test_loconav_primary_total(self):
        start = datetime.utcnow() - timedelta(hours=2)
        end = datetime.utcnow()

        data = {"data": {"fuel_consumption": {"value": 7.75}}}
        with patch("wareApp.fuel_providers.requests.get") as mock_get:
            mock_get.return_value = MockResponse(200, data)
            val = fp.fetch_loconav_fuel("veh1", start, end)
            self.assertEqual(val, 7.75)

    def test_loconav_report_payload(self):
        start = datetime.utcnow() - timedelta(hours=2)
        end = datetime.utcnow()

        report = {
            "alerts": {
                "REFUELING_ALERT": [{"timestamp": 1620000000, "value": 12.3}],
                "POSSIBLE_FUEL_THEFT_ALERT": [{"timestamp": 1620001000, "value": 1.2}],
            }
        }

        def side_effect(url, params=None, headers=None, timeout=None):
            if "marketplace.loconav.com/api/v1/vehicles/fuel?" in url:
                return MockResponse(200, report)
            return MockResponse(404, {})

        with patch("wareApp.fuel_providers.requests.get", side_effect=side_effect):
            payload = fp.fetch_loconav_report("veh1", start, end)

        self.assertEqual(payload, report)

    def test_detect_refuel_and_theft(self):
        alerts = {
            "alerts": {
                "REFUELING_ALERT": [{"timestamp": 1600000000, "value": 10}],
                "POSSIBLE_FUEL_THEFT_ALERT": [{"timestamp": 1600001000, "value": 5}],
            }
        }
        ref = fp.detect_refuel_from_alerts(alerts)
        theft = fp.detect_theft_from_alerts(alerts)
        self.assertEqual(len(ref), 1)
        self.assertEqual(ref[0]["value"], 10)
        self.assertEqual(len(theft), 1)
        self.assertEqual(theft[0]["value"], 5)

    def test_detect_suspicious_fuel(self):
        self.assertTrue(fp.detect_suspicious_fuel(100, 130))
        self.assertFalse(fp.detect_suspicious_fuel(100, 80))


if __name__ == "__main__":
    unittest.main()
