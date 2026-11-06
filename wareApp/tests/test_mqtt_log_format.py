from datetime import date, datetime

from django.test import SimpleTestCase

from wareApp.mqtt.log_format import day_ranges, hour_ranges, missing_hours


class LogFormatTests(SimpleTestCase):
    def test_missing_hours_is_inclusive_of_the_last_missing_hour(self):
        self.assertEqual(
            missing_hours(datetime(2026, 10, 19, 9), datetime(2026, 10, 19, 19)),
            "2026-10-19 09:00→18:00 (10 h)",
        )

    def test_missing_hours_across_midnight_shows_both_dates(self):
        self.assertEqual(
            missing_hours(datetime(2026, 10, 18, 22), datetime(2026, 10, 19, 2)),
            "2026-10-18 22:00→2026-10-19 01:00 (4 h)",
        )

    def test_hour_ranges_merge_consecutive_hours(self):
        hours = [datetime(2026, 10, 1, h) for h in (0, 1, 2, 5)]
        self.assertEqual(
            hour_ranges(hours),
            "2026-10-01 00:00→02:00 (3 h), 2026-10-01 05:00 (1 h)",
        )

    def test_day_ranges_merge_consecutive_days(self):
        days = [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]
        self.assertEqual(day_ranges(days), "2026-09-30→2026-10-02 (3 d), 2026-10-05")

    def test_empty_and_long_lists(self):
        self.assertEqual(hour_ranges([]), "-")
        many = [datetime(2026, 10, 1, h) for h in range(0, 24, 2)]
        self.assertTrue(hour_ranges(many).endswith("+6 more ranges"))
