import unittest

from wareApp.dg_fuel.normalization import as_float, epoch_milliseconds


class DgFuelNormalizationTests(unittest.TestCase):
    def test_as_float_accepts_numeric_provider_values(self):
        self.assertEqual(as_float(12), 12.0)
        self.assertEqual(as_float(" 12.5 "), 12.5)

    def test_as_float_rejects_missing_and_invalid_values(self):
        self.assertIsNone(as_float(None))
        self.assertIsNone(as_float(True))
        self.assertIsNone(as_float("not-a-number"))

    def test_epoch_milliseconds_preserves_milliseconds(self):
        self.assertEqual(epoch_milliseconds(1788115579000), 1788115579000)

    def test_epoch_milliseconds_converts_seconds(self):
        self.assertEqual(epoch_milliseconds("1788115579"), 1788115579000)

    def test_epoch_milliseconds_parses_roadcast_iso_timestamp(self):
        self.assertEqual(
            epoch_milliseconds("2026-08-30T18:44:40.000000+0000"),
            1788115480000,
        )

    def test_epoch_milliseconds_rejects_invalid_values(self):
        self.assertIsNone(epoch_milliseconds(None))
        self.assertIsNone(epoch_milliseconds(False))
        self.assertIsNone(epoch_milliseconds("unknown"))


if __name__ == "__main__":
    unittest.main()