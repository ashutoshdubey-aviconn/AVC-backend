from datetime import date, datetime, time
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from wareApp.models import AisleGroup, AlarmNotifications, DailySiteReading, HourlySiteReading, Site, SiteBaseline
from wareApp.mqtt.services.consumption_alarms import evaluate_daily_alarms, evaluate_days

DAY = date(2026, 10, 15)


@patch("wareApp.mqtt.services.consumption_alarms.notify")
class DailyAlarmRuleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Alarm rules site", site_type=1)
        self.aisle = self.make_aisle("HB-Part-1")

    def make_aisle(self, name):
        aisle = AisleGroup.objects.create(site=self.site, aisleGroupName=name, is_active=True)
        aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=aisle.attached_leg_id, baseline_value=200.0,
            working_hours=24, baseline_from=date(2026, 1, 1),
        )
        return aisle

    def reading(self, kwh, aisle=None, day=DAY):
        aisle = aisle or self.aisle
        return DailySiteReading.objects.create(
            associated_Site=self.site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
            unit_consumption=kwh, reading_for=day, is_visible=True,
        )

    def types(self):
        return sorted(AlarmNotifications.objects.values_list("Alarm_type", flat=True))

    def test_high_defaults_to_75_percent_of_baseline(self, notify):
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(149.0)), [])
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(150.0, day=date(2026, 10, 16))), ["High Consumption"])
        self.assertEqual(self.types(), [7])
        self.assertEqual(notify.call_args.args[1], "High Consumption Alarm")

    def test_configured_units_win_over_percent(self, notify):
        self.site.high_consumption_units = 250.0
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(200.0)), [])
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(250.0, day=date(2026, 10, 16))), ["High Consumption"])

    def test_bypass_supersedes_high(self, notify):
        self.site.high_consumption_units = 250.0
        self.site.bypass_consumption_units = 400.0
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(450.0)), ["Bypassed"])
        self.assertEqual(self.types(), [11])

    def test_low_consumption_against_baseline(self, notify):
        self.site.min_threshold_value = 90  # alarm below 10 % of baseline = 20 kWh
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(25.0)), [])
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(19.0, day=date(2026, 10, 16))), ["Low Consumption"])

    def test_no_low_alarm_without_site_threshold(self, notify):
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(1.0)), [])

    def test_evaluating_twice_stores_once(self, notify):
        reading = self.reading(160.0)
        evaluate_daily_alarms(self.site, self.aisle, reading)
        evaluate_daily_alarms(self.site, self.aisle, reading)
        self.assertEqual(self.types(), [7])
        notify.assert_called_once()

    def test_no_baseline_or_before_baseline_start(self, notify):
        aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="No-Base", is_active=True)
        aisle.refresh_from_db()
        self.assertEqual(evaluate_daily_alarms(self.site, aisle, self.reading(999.0, aisle=aisle)), [])
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(999.0, day=date(2025, 12, 31))), [])

    def hourly(self, aisle, hours, kwh=1.0):
        for hour in hours:
            start = datetime.combine(DAY, time(hour))
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
                unit_consumption=kwh, reading_from=start, reading_to=start.replace(minute=59, second=59),
            )

    def configure_window(self, start_hour, end_hour, hours):
        self.site.nl_operation_hours = hours
        self.site.nl_operation_start_time = time(start_hour)
        self.site.nl_operation_end_time = time(end_hour)

    def test_operation_hours_outside_window(self, notify):
        self.configure_window(9, 18, 9)
        self.hourly(self.aisle, [9, 10, 11, 20])
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(50.0)), ["Operation Hours Increased"])
        self.assertIn("20:00", str(notify.call_args.args[3]))

    def test_operation_hours_names_cause_of_high_consumption(self, notify):
        self.configure_window(9, 18, 9)
        self.hourly(self.aisle, list(range(8, 20)))
        stored = evaluate_daily_alarms(self.site, self.aisle, self.reading(180.0))
        self.assertEqual(stored, ["Operation Hours Increased", "High Consumption"])
        high = AlarmNotifications.objects.get(Alarm_type=7)
        self.assertIn("operation hours increased", high.to_do)

    def test_operation_hours_window_across_midnight_and_el_excluded(self, notify):
        self.configure_window(22, 6, 8)
        self.hourly(self.aisle, [22, 23, 0, 5])
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(50.0)), [])
        el = self.make_aisle("RPC-EL")
        self.hourly(el, [10, 11, 12])
        self.assertEqual(evaluate_daily_alarms(self.site, el, self.reading(50.0, aisle=el)), [])

    def test_operation_hours_not_evaluated_without_window(self, notify):
        self.hourly(self.aisle, list(range(24)))
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(50.0)), [])

    def test_evaluate_days_skips_today_and_old_days(self, notify):
        from datetime import timedelta

        today = datetime.now().date()
        recent, old = today - timedelta(days=2), today - timedelta(days=30)
        for day in (recent, old, today):
            self.reading(160.0, day=day)
        stored = evaluate_days(self.site, self.aisle, [recent, old, today])
        self.assertEqual(stored, [f"{recent} High Consumption"])


class RecoveryReevaluatesAlarmsTests(TestCase):
    def test_daily_recovery_reevaluates_written_days(self):
        from wareApp.mqtt import daily_consumption_recovery

        cache.clear()
        site = Site.objects.create(site_name="Recovery alarm site", site_type=1)
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="HB-1", is_active=True)
        aisle.refresh_from_db()
        message = (
            f"Aisle_group_id : {aisle.attached_leg_id}; Recovery_Dates : 2026-10-14,2026-10-15,;"
            " Unit_consumptions : 10.5,12.0,; GW_Total_cumulative : 100"
        )
        with patch(
            "wareApp.mqtt.daily_consumption_recovery.evaluate_days", return_value=[]
        ) as evaluate:
            daily_consumption_recovery.handle_daily_consumption_recovery_message(
                site, site.id, "gw-1", message
            )

        evaluate.assert_called_once()
        self.assertEqual(sorted(evaluate.call_args.args[2]), [date(2026, 10, 14), date(2026, 10, 15)])
