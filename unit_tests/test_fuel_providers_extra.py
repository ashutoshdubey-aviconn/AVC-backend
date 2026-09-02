import unittest

from wareApp.fuel_providers import (
    detect_refuel_from_alerts,
    detect_theft_from_alerts,
    detect_suspicious_fuel,
)


class FuelProvidersParseTests(unittest.TestCase):
    def test_detect_refuel_with_string_timestamp_and_value(self):
        alerts = {
            "alerts": {
                "REFUELING_ALERT": [{"timestamp": "1620000000", "value": "12.3"}]
            }
        }
        out = detect_refuel_from_alerts(alerts)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0]["timestamp"], int)
        self.assertAlmostEqual(out[0]["value"], 12.3)

    def test_detect_theft_handles_missing_timestamp(self):
        alerts = {
            "alerts": {
                "POSSIBLE_FUEL_THEFT_ALERT": [{"timestamp": None, "value": "1.2"}]
            }
        }
        out = detect_theft_from_alerts(alerts)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["timestamp"])
        self.assertAlmostEqual(out[0]["value"], 1.2)

    def test_detect_suspicious_borderline(self):
        self.assertFalse(detect_suspicious_fuel(50, 50 * 1.2))
        self.assertTrue(detect_suspicious_fuel(50, 61))


if __name__ == "__main__":
    unittest.main()
