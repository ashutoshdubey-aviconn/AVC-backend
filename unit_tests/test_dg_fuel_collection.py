import unittest
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


if __name__ == "__main__":
    unittest.main()