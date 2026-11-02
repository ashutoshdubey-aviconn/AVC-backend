from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from wareApp.models import AisleGroup, AlarmNotifications, DailySiteReading, HourlySiteReading, Site, SiteBaseline
from wareApp.mqtt.services.consumption_alarms import check_intraday_bypass, evaluate_daily_alarms, evaluate_days

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
        self.site.bypass_consumption_units = 1000.0  # keep automatic bypass out of this test
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(200.0)), [])
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(250.0, day=date(2026, 10, 16))), ["High Consumption"])

    def test_bypass_supersedes_high(self, notify):
        self.site.high_consumption_units = 250.0
        self.site.bypass_consumption_units = 400.0
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(450.0)), ["Bypassed"])
        self.assertEqual(self.types(), [11])

    def test_bypass_is_automatic_at_full_baseline(self, notify):
        # Baseline 200 kWh: 75 %..<100 % is High, >= 100 % (no saving) is Bypassed.
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(199.0)), ["High Consumption"])
        self.assertEqual(
            evaluate_daily_alarms(self.site, self.aisle, self.reading(200.0, day=date(2026, 10, 16))),
            ["Bypassed"],
        )
        self.assertEqual(self.types(), [7, 11])
        self.assertIn("100 % of baseline", notify.call_args.args[3][-1][1])

    @override_settings(ALARM_BYPASS_DEFAULT_PERCENT=120)
    def test_bypass_percent_is_a_setting(self, notify):
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(230.0)), ["High Consumption"])
        self.assertEqual(
            evaluate_daily_alarms(self.site, self.aisle, self.reading(240.0, day=date(2026, 10, 16))),
            ["Bypassed"],
        )

    def test_site_bypass_value_overrides_percent(self, notify):
        self.site.bypass_consumption_units = 500.0
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.reading(300.0)), ["High Consumption"])
        self.assertEqual(
            evaluate_daily_alarms(self.site, self.aisle, self.reading(600.0, day=date(2026, 10, 16))),
            ["Bypassed"],
        )
        self.assertIn("site setting", notify.call_args.args[3][-1][1])

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


@patch("wareApp.mqtt.services.consumption_alarms.notify")
class IntradayBypassTests(TestCase):
    """Bypassed raised during the day when the running total crosses the baseline."""

    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Intraday site", site_type=1)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="HDR-GF", is_active=True)
        self.aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=self.aisle.attached_leg_id, baseline_value=200.0,
            working_hours=24, baseline_from=date(2026, 1, 1),
        )

    def bypassed(self):
        return list(AlarmNotifications.objects.filter(Alarm_type=11).values_list("created_time", flat=True))

    def test_raised_once_when_the_running_total_crosses_the_baseline(self, notify):
        at = datetime(2026, 10, 15, 16, 30)
        self.assertFalse(check_intraday_bypass(self.site, self.aisle, DAY, 140.0, now=at))
        self.assertTrue(check_intraday_bypass(self.site, self.aisle, DAY, 205.0, now=at))
        self.assertFalse(check_intraday_bypass(self.site, self.aisle, DAY, 240.0, now=at))
        self.assertEqual(self.bypassed(), [datetime(2026, 10, 15)])
        self.assertEqual(AlarmNotifications.objects.get(Alarm_type=11).Alarm_priority, 0)  # High
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(notify.call_args.args[1], "Bypassed Alarm")
        self.assertIn("during the day, 16:30", AlarmNotifications.objects.get().to_do)

    def test_high_during_the_day_then_bypassed_closes_it(self, notify):
        at = datetime(2026, 10, 15, 14, 0)
        self.assertTrue(check_intraday_bypass(self.site, self.aisle, DAY, 155.0, now=at))  # 75 % of 200
        self.assertFalse(check_intraday_bypass(self.site, self.aisle, DAY, 170.0, now=at))
        high = AlarmNotifications.objects.get(Alarm_type=7)
        self.assertEqual((high.is_active, high.Alarm_priority, notify.call_args.args[1]),
                         (True, 0, "High Consumption Alarm"))
        cache.delete(f"intraday:{self.site.id}:{self.aisle.id}:{DAY:%Y%m%d}:recheck")
        self.assertTrue(check_intraday_bypass(self.site, self.aisle, DAY, 205.0, now=at + timedelta(hours=2)))
        high.refresh_from_db()
        self.assertFalse(high.is_active)
        self.assertEqual(self.bypassed(), [datetime(2026, 10, 15)])
        self.assertEqual(notify.call_count, 2)

    def test_next_day_is_a_new_alarm_and_e_mailed_again(self, notify):
        check_intraday_bypass(self.site, self.aisle, DAY, 205.0)
        AlarmNotifications.objects.filter(Alarm_type=11).update(is_active=False)  # closed at day end
        check_intraday_bypass(self.site, self.aisle, DAY, 230.0)  # same day: still one
        check_intraday_bypass(self.site, self.aisle, DAY + timedelta(days=1), 201.0)
        self.assertEqual(self.bypassed(), [datetime(2026, 10, 15), datetime(2026, 10, 16)])
        self.assertEqual(notify.call_count, 2)

    def test_day_end_check_does_not_duplicate_or_add_high(self, notify):
        check_intraday_bypass(self.site, self.aisle, DAY, 205.0)
        reading = DailySiteReading.objects.create(
            associated_Site=self.site, aisle_group=self.aisle, leg_id=self.aisle.attached_leg_id,
            unit_consumption=260.0, reading_for=DAY, is_visible=True,
        )
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, reading), [])
        self.assertEqual(sorted(AlarmNotifications.objects.values_list("Alarm_type", flat=True)), [11])

    def test_off_is_honoured(self, notify):
        from wareApp.models import AlarmSetting
        AlarmSetting.objects.create(site=self.site, alarm_type=11, mode=AlarmSetting.OFF)
        AlarmSetting.objects.create(site=self.site, alarm_type=7, mode=AlarmSetting.OFF)
        self.assertFalse(check_intraday_bypass(self.site, self.aisle, DAY, 500.0))
        self.assertEqual(self.bypassed(), [])


@patch("wareApp.mqtt.services.consumption_alarms.notify")
class UnreliableDataTests(TestCase):
    """Spike hours do not count; no Bypassed / High on a Meter Reading Issue day."""

    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Spike site", site_type=1)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="F1-C-Section-EL", is_active=True)
        self.aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=self.aisle.attached_leg_id, baseline_value=48.0,
            working_hours=24, baseline_from=date(2026, 1, 1),
        )

    def hours(self, values, day=DAY, first_hour=0):
        for offset, kwh in enumerate(values):
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=self.aisle.attached_leg_id,
                unit_consumption=kwh, reading_from=datetime.combine(day, time(first_hour + offset)),
                reading_to=datetime.combine(day, time(first_hour + offset, 59, 59)), is_visible=True,
            )

    def daily(self, kwh, day=DAY):
        return DailySiteReading.objects.create(
            associated_Site=self.site, aisle_group=self.aisle, leg_id=self.aisle.attached_leg_id,
            unit_consumption=kwh, reading_for=day, is_visible=True,
        )

    def test_hour_above_the_whole_daily_baseline_is_not_counted(self, notify):
        self.hours([1.0] * 23, day=date(2026, 10, 14), first_hour=1)  # yesterday 01-23
        self.hours([1.0] * 4 + [3290.0] + [1.0] * 5)  # today: meter jump at 04:00
        self.assertFalse(check_intraday_bypass(self.site, self.aisle, DAY, 3299.0))
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.daily(3299.0)), [])
        self.assertFalse(AlarmNotifications.objects.exists())

    def test_first_hour_after_a_gap_is_not_counted(self, notify):
        self.hours([1.0] * 6, day=date(2026, 10, 14), first_hour=12)  # yesterday until 17:00, then nothing
        self.hours([40.0, 1.0, 1.0], first_hour=10)  # today 10:00 carries the gap
        self.assertFalse(check_intraday_bypass(self.site, self.aisle, DAY, 42.0 + 10))
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.daily(52.0)), [])

    def test_normal_sized_hour_after_our_own_downtime_still_counts(self, notify):
        # No readings yesterday (our server was down); today's hours are all normal.
        self.hours([2.5] * 20)
        self.assertTrue(check_intraday_bypass(self.site, self.aisle, DAY, 50.0))

    def test_normal_hours_still_raise_bypassed(self, notify):
        self.hours([1.0] * 23, day=date(2026, 10, 14), first_hour=1)
        self.hours([2.5] * 20)  # 50 kWh >= 48 baseline, no spike
        self.assertTrue(check_intraday_bypass(self.site, self.aisle, DAY, 50.0))

    def test_no_bypassed_or_high_on_a_meter_reading_issue_day(self, notify):
        self.hours([1.0] * 23, day=date(2026, 10, 14), first_hour=1)
        self.hours([2.5] * 20)
        AlarmNotifications.objects.create(
            site_id=self.site, aisle_group=self.aisle, Alarm_type=10, object_type=4,
            created_time=datetime.combine(DAY, time(12, 0)), to_do="lower meter reading reported",
        )
        self.assertFalse(check_intraday_bypass(self.site, self.aisle, DAY, 50.0))
        self.assertEqual(evaluate_daily_alarms(self.site, self.aisle, self.daily(50.0)), [])
        self.assertEqual(list(AlarmNotifications.objects.values_list("Alarm_type", flat=True)), [10])
