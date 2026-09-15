import unittest
from datetime import datetime
from types import SimpleNamespace

from wareApp.dg_fuel.collection import collect_loconav_levels, collect_roadcast_levels


class DgFuelCollectionTests(unittest.TestCase):
    def test_collects_loconav_sample_for_matching_site(self):
        site = SimpleNamespace(id=76, partner_dg_fuel_id="DCGenerator-01")
        result = collect_loconav_levels(
            [site],
            lambda vehicle: {
                "data": [
                    {
                        "vehicle_number": "DCGENERATOR-01",
                        "fuel_in_liters": 356.16,
                        "timestamp": 1788115579000,
                    }
                ]
            },
        )
        self.assertEqual(result["failed_site_ids"], [])
        self.assertEqual(len(result["samples"]), 1)
        self.assertEqual(result["samples"][0]["site"], site)
        self.assertEqual(result["samples"][0]["source"], "loconav")

    def test_reports_unavailable_loconav_site(self):
        site = SimpleNamespace(id=92, partner_dg_fuel_id="DCGENERATORLucknow")
        result = collect_loconav_levels([site], lambda vehicle: {"data": []})
        self.assertEqual(result["samples"], [])
        self.assertEqual(result["failed_site_ids"], [])
        self.assertEqual(result["expired_site_ids"], [92])

    def test_maps_roadcast_levels_and_reports_missing_devices(self):
        present = SimpleNamespace(id=118, partner_dg_fuel_id="353691840557010")
        absent = SimpleNamespace(id=124, partner_dg_fuel_id="353201353997221")
        result = collect_roadcast_levels(
            [present, absent],
            lambda: {
                "data": [
                    {
                        "deviceImei": "353691840557010",
                        "fuel": 275.46,
                        "lastUpdate": "2026-08-30T18:44:40.000000+0000",
                    }
                ]
            },
        )
        self.assertEqual(len(result["samples"]), 1)
        self.assertEqual(result["samples"][0]["site"], present)
        self.assertEqual(result["missing_vehicle_ids"], ["353201353997221"])
        self.assertEqual(result["expired_vehicle_ids"], ["353201353997221"])

    def test_only_current_roadcast_samples_are_persistable(self):
        current_site = SimpleNamespace(id=118, partner_dg_fuel_id="353691840557010")
        stale_site = SimpleNamespace(id=153, partner_dg_fuel_id="353691846234838")
        result = collect_roadcast_levels(
            [current_site, stale_site],
            lambda: {
                "data": [
                    {
                        "deviceImei": "353691840557010",
                        "fuel": 275.46,
                        "lastUpdate": "2026-09-14T06:44:40.000000+0000",
                        "status": "online",
                    },
                    {
                        "deviceImei": "353691846234838",
                        "fuel": 10.53,
                        "lastUpdate": "2026-09-10T05:07:18.000000+0000",
                        "status": "offline",
                    },
                ],
                "error": [
                    {
                        "error": "Subscription expired",
                        "message": "The device with ID 281311 and name '124' has an expired subscription",
                    }
                ],
            },
            reference_date=datetime(2026, 9, 14),
        )
        self.assertEqual(len(result["samples"]), 1)
        self.assertEqual(result["samples"][0]["site"], current_site)
        self.assertEqual(result["stale_vehicle_ids"], ["353691846234838"])
        self.assertEqual(len(result["subscription_expired_errors"]), 1)


if __name__ == "__main__":
    unittest.main()
