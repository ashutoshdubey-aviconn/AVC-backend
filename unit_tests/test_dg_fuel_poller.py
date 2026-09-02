import unittest
from types import SimpleNamespace

from wareApp.dg_fuel.poller import collect_level_cycle


class DgFuelPollerTests(unittest.TestCase):
    def test_dry_run_reports_proposed_samples_without_writing(self):
        loconav_site = SimpleNamespace(
            id=76, partner_dg_provider="loconav", partner_dg_fuel_id="DCGenerator-01"
        )
        roadcast_site = SimpleNamespace(
            id=118, partner_dg_provider="roadcast", partner_dg_fuel_id="353691840557010"
        )
        result = collect_level_cycle(
            [loconav_site, roadcast_site],
            lambda vehicle: {
                "data": [
                    {
                        "vehicle_number": vehicle,
                        "fuel_in_liters": 356.16,
                        "timestamp": 1788115579000,
                    }
                ]
            },
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
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["proposed_samples"], 2)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["existing"], 0)
        self.assertFalse(result["roadcast_provider_request_failed"])

    def test_dry_run_reports_missing_roadcast_device(self):
        roadcast_site = SimpleNamespace(
            id=124, partner_dg_provider="roadcast", partner_dg_fuel_id="353201353997221"
        )
        result = collect_level_cycle(
            [roadcast_site], lambda vehicle: {"data": []}, lambda: {"data": []}
        )
        self.assertEqual(result["proposed_samples"], 0)
        self.assertEqual(result["roadcast_missing_vehicle_ids"], ["353201353997221"])
        self.assertEqual(result["roadcast_expired_vehicle_ids"], ["353201353997221"])
        self.assertFalse(result["roadcast_provider_request_failed"])

    def test_dry_run_reports_loconav_expired_device_separately(self):
        loconav_site = SimpleNamespace(
            id=92, partner_dg_provider="loconav", partner_dg_fuel_id="DCGENERATORLucknow"
        )
        result = collect_level_cycle(
            [loconav_site], lambda vehicle: {"data": []}, lambda: {"data": []}
        )
        self.assertEqual(result["proposed_samples"], 0)
        self.assertEqual(result["loconav_failed_site_ids"], [])
        self.assertEqual(result["loconav_expired_site_ids"], [92])
        self.assertEqual(result["unavailable_device_ids"], [92])

    def test_dry_run_reports_roadcast_request_failure_separately(self):
        roadcast_site = SimpleNamespace(
            id=118, partner_dg_provider="roadcast", partner_dg_fuel_id="353691840557010"
        )
        result = collect_level_cycle(
            [roadcast_site],
            lambda vehicle: {"data": []},
            lambda: (_ for _ in ()).throw(ConnectionError("Roadcast unavailable")),
        )
        self.assertTrue(result["roadcast_provider_request_failed"])
        self.assertEqual(result["roadcast_missing_vehicle_ids"], [])


if __name__ == "__main__":
    unittest.main()