import unittest
from datetime import datetime

from wareApp.dg_fuel.providers import (
    extract_roadcast_subscription_expired_errors,
    parse_loconav_current_levels,
    parse_roadcast_current_levels,
    parse_roadcast_report,
)


class DgFuelProviderParserTests(unittest.TestCase):
    def test_parses_loconav_current_level(self):
        levels = parse_loconav_current_levels(
            {
                "status": True,
                "data": [
                    {
                        "vehicle_number": "DCGenerator-01",
                        "fuel_in_liters": 356.16,
                        "value_in_percentage": 79.15,
                        "fuel_capacity": 450,
                        "timestamp": 1788115579000,
                    }
                ],
            }
        )
        self.assertEqual(
            levels,
            [
                {
                    "vehicle_number": "DCGenerator-01",
                    "fuel_liters": 356.16,
                    "fuel_capacity": 450.0,
                    "percentage": 79.15,
                    "epoch_ms": 1788115579000,
                }
            ],
        )

    def test_skips_invalid_loconav_level(self):
        self.assertEqual(
            parse_loconav_current_levels(
                {"data": [{"vehicle_number": "PBDN450", "fuel_in_liters": "bad"}]}
            ),
            [],
        )

    def test_parses_allowed_roadcast_current_level(self):
        levels = parse_roadcast_current_levels(
            {
                "data": [
                    {
                        "deviceImei": "353691840557010",
                        "fuel": "275.4660194174757",
                        "lastUpdate": "2026-08-30T18:44:40.000000+0000",
                        "ignition": "true",
                    },
                    {
                        "deviceImei": "unmapped",
                        "fuel": 10,
                        "lastUpdate": "2026-08-30T18:44:40.000000+0000",
                    },
                ]
            },
            allowed_imeis=["353691840557010"],
        )
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0]["vehicle_number"], "353691840557010")
        self.assertAlmostEqual(levels[0]["fuel_liters"], 275.4660194174757)
        self.assertEqual(levels[0]["epoch_ms"], 1788115480000)
        self.assertEqual(levels[0]["telemetry_state"], "CURRENT")
        self.assertTrue(levels[0]["is_current_sample"])
        self.assertEqual(levels[0]["ignition"], "true")

    def test_parses_offline_roadcast_current_level_as_diagnostic(self):
        levels = parse_roadcast_current_levels(
            {
                "data": [
                    {
                        "deviceImei": "353691846234838",
                        "fuel": 10.533980582524272,
                        "lastUpdate": "2026-09-14T05:07:18.000000+0000",
                        "status": "offline",
                    }
                ]
            },
            allowed_imeis=["353691846234838"],
            reference_date=datetime(2026, 9, 14),
        )
        self.assertEqual(levels[0]["telemetry_state"], "OFFLINE")
        self.assertFalse(levels[0]["is_current_sample"])

    def test_missing_last_update_is_skipped(self):
        self.assertEqual(
            parse_roadcast_current_levels(
                {"data": [{"deviceImei": "353691840557010", "fuel": 10}]},
                allowed_imeis=["353691840557010"],
                reference_date=datetime(2026, 9, 14),
            ),
            [],
        )

    def test_classifies_stale_roadcast_current_level(self):
        levels = parse_roadcast_current_levels(
            {
                "data": [
                    {
                        "deviceId": 346791,
                        "deviceImei": "353691846234838",
                        "deviceFixTime": "2026-09-10T05:05:22.000+0000",
                        "deviceTime": "2026-09-10T05:05:22.000+0000",
                        "fuel": 10.533980582524272,
                        "ignition": "false",
                        "lastUpdate": "2026-09-10T05:07:18.000000+0000",
                        "latitude": "28.3945383",
                        "longitude": "76.6999316",
                        "name": "153",
                        "status": "offline",
                        "vehicle_status": "Dormant",
                    }
                ]
            },
            allowed_imeis=["353691846234838"],
            reference_date=datetime(2026, 9, 14),
        )
        self.assertEqual(levels[0]["telemetry_state"], "STALE")
        self.assertFalse(levels[0]["is_current_sample"])

    def test_extracts_subscription_expired_errors(self):
        errors = extract_roadcast_subscription_expired_errors(
            {
                "error": [
                    {
                        "error": "Subscription expired",
                        "message": "The device with ID 281311 and name '124' has an expired subscription",
                    }
                ]
            }
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(
            errors[0]["message"],
            "The device with ID 281311 and name '124' has an expired subscription",
        )

    def test_parses_roadcast_report_and_parallel_events(self):
        report = parse_roadcast_report(
            {
                "initial_fuel_level": 270.57,
                "fuel_level_at_end": 275.47,
                "fuel_consumed": 24.49,
                "fuel_data": [{"fuel": 270.57, "time": 1788028800}],
                "fuel_fillings": {
                    "fuel_amounts": [29.39],
                    "refill_time": [1788064800],
                },
                "fuel_stolen_details": {
                    "stolen_amounts": [1.25],
                    "theft_time": [1788072000000],
                },
            }
        )
        self.assertEqual(report["fuel_consumed"], 24.49)
        self.assertEqual(report["fuel_levels"][0]["epoch_ms"], 1788028800000)
        self.assertEqual(
            report["refuels"], [{"fuel_liters": 29.39, "epoch_ms": 1788064800000}]
        )
        self.assertEqual(
            report["thefts"], [{"fuel_liters": 1.25, "epoch_ms": 1788072000000}]
        )

    def test_drops_synthetic_leading_zero_fuel_sample(self):
        report = parse_roadcast_report(
            {
                "initial_fuel_level": 41.06,
                "fuel_level_at_end": 41.12,
                "fuel_consumed": 0,
                "fuel_data": [
                    {"fuel": 0.0, "time": 1788115020},
                    {"fuel": 37.9, "time": 1788115200},
                    {"fuel": 37.82, "time": 1788115260},
                ],
            }
        )
        self.assertEqual(
            report["fuel_levels"],
            [
                {"fuel_liters": 37.9, "epoch_ms": 1788115200000},
                {"fuel_liters": 37.82, "epoch_ms": 1788115260000},
            ],
        )

    def test_keeps_real_zero_fuel_sample_when_no_synthetic_signals_exist(self):
        report = parse_roadcast_report(
            {
                "fuel_consumed": 0,
                "fuel_data": [{"fuel": 0.0, "time": 1788115020}],
            }
        )
        self.assertEqual(
            report["fuel_levels"],
            [{"fuel_liters": 0.0, "epoch_ms": 1788115020000}],
        )

    def test_parses_roadcast_refill_window_dicts(self):
        report = parse_roadcast_report(
            {
                "fuel_consumed": 2.94,
                "fuel_fill_count": 1,
                "fuel_fillings": {
                    "fuel_amounts": [8.6],
                    "refill_time": [
                        {
                            "start_time": "2026-09-14 17:07:22",
                            "end_time": "2026-09-14 17:14:52",
                        }
                    ],
                },
            }
        )
        self.assertEqual(
            report["refuels"], [{"fuel_liters": 8.6, "epoch_ms": 1789386292000}]
        )

    def test_roadcast_report_handles_missing_event_containers(self):
        report = parse_roadcast_report({"fuel_consumed": 0})
        self.assertEqual(report["fuel_consumed"], 0.0)
        self.assertEqual(report["refuels"], [])
        self.assertEqual(report["thefts"], [])


if __name__ == "__main__":
    unittest.main()
