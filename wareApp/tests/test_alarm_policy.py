"""Alarm recipients, per-site settings (Auto / Manual / Off) and the repeat rule."""

from datetime import date, datetime, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from wareApp import gateway_overheat
from wareApp.mqtt.services import alarm_policy
from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    AlarmSetting,
    DailySiteReading,
    Site,
    SiteBaseline,
)
from wareApp.mqtt import load
from wareApp.mqtt.services import alarms
from wareApp.mqtt.services.consumption_alarms import evaluate_daily_alarms


class RecipientTests(TestCase):
    """Lists from wareApp/mqtt/services/alarm_recipients.py."""

    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Site A", site_type=1)
        self.other = Site.objects.create(site_name="Site B", site_type=1)
        lists = mock.patch.multiple(
            "wareApp.mqtt.services.alarm_recipients",
            SOFTWARE_TEAM=["dev1@example.com", " dev2@example.com "],
            GROUND_TEAM={self.site.id: ["ground-a@example.com", "dev1@example.com"]},
        )
        lists.start()
        self.addCleanup(lists.stop)

    def test_software_gets_every_site_and_ground_only_its_sites(self):
        self.assertEqual(
            alarm_policy.recipients(self.site.id, 7),
            ["dev1@example.com", "dev2@example.com", "ground-a@example.com"],
        )
        self.assertEqual(alarm_policy.recipients(self.other.id, 7), ["dev1@example.com", "dev2@example.com"])

    def test_groups_can_be_switched_off_per_site_and_type(self):
        AlarmSetting.objects.create(site=self.site, alarm_type=2, email_software=False)
        self.assertEqual(alarm_policy.recipients(self.site.id, 2), ["ground-a@example.com", "dev1@example.com"])
        AlarmSetting.objects.create(site=self.site, alarm_type=7, email_ground=False)
        self.assertEqual(alarm_policy.recipients(self.site.id, 7), ["dev1@example.com", "dev2@example.com"])

    @override_settings(ALARM_EMAIL_DEFAULT_TO=["old@example.com"])
    def test_former_list_is_used_while_both_lists_are_empty(self):
        with mock.patch.multiple(
            "wareApp.mqtt.services.alarm_recipients", SOFTWARE_TEAM=[], GROUND_TEAM={}
        ):
            self.assertEqual(alarm_policy.recipients(self.site.id, 7), ["old@example.com"])


class RepeatRuleTests(TestCase):
    def test_should_email(self):
        self.assertTrue(alarm_policy.should_email(None, 260, True, 5))
        self.assertFalse(alarm_policy.should_email(260, 270, True, 5))  # 3.8 % worse
        self.assertTrue(alarm_policy.should_email(260, 274, True, 5))  # 5.4 % worse
        self.assertFalse(alarm_policy.should_email(260, 240, True, 5))  # better
        self.assertFalse(alarm_policy.should_email(0.80, 0.77, False, 5))  # PF 3.75 % lower
        self.assertTrue(alarm_policy.should_email(0.80, 0.75, False, 5))


class PowerAlarmRepeatTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Power site", site_type=1)
        notify = mock.patch.object(alarms, "notify")
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def raise_high(self, volts):
        return alarms.raise_power_alarm(
            self.site, 0, power_source="Mains Supply", repeat_every=timedelta(minutes=30),
            email=("send", {"v": volts}), severity=volts,
        )

    def age_last_occurrence(self, **extra):
        AlarmNotifications.objects.update(last_notified_at=datetime.now() - timedelta(hours=1), **extra)

    def test_repeat_near_the_last_e_mail_is_counted_but_not_e_mailed(self):
        self.raise_high(260.0)
        self.age_last_occurrence()
        self.raise_high(265.0)  # 1.9 % worse
        row = AlarmNotifications.objects.get()
        self.assertEqual((row.occurrences, row.notified_value), (2, 260.0))
        self.assertEqual(self.notify.call_count, 1)

    def test_clearly_worse_repeat_is_e_mailed(self):
        self.raise_high(260.0)
        self.age_last_occurrence()
        self.raise_high(280.0)  # 7.7 % worse
        self.assertEqual(self.notify.call_count, 2)
        self.assertEqual(AlarmNotifications.objects.get().notified_value, 280.0)

    def test_next_day_with_the_same_value_is_not_e_mailed_and_keeps_the_last_value(self):
        self.raise_high(260.0)
        yesterday = datetime.now() - timedelta(days=1)
        self.age_last_occurrence(created_time=yesterday, last_seen=datetime.now() - timedelta(hours=2))
        self.raise_high(261.0)
        self.assertEqual(AlarmNotifications.objects.count(), 2)
        self.assertEqual(self.notify.call_count, 1)
        self.assertEqual(AlarmNotifications.objects.order_by("-id").first().notified_value, 260.0)

    def test_after_the_alarm_cleared_it_is_e_mailed_again(self):
        self.raise_high(260.0)
        two_days_ago = datetime.now() - timedelta(days=2)
        self.age_last_occurrence(created_time=two_days_ago, last_seen=two_days_ago)
        self.raise_high(260.0)
        self.assertEqual(self.notify.call_count, 2)

    def test_tolerance_can_be_set_per_site_and_type(self):
        AlarmSetting.objects.create(site=self.site, alarm_type=0, repeat_tolerance_percent=1)
        self.raise_high(260.0)
        self.age_last_occurrence()
        self.raise_high(265.0)  # 1.9 % worse > 1 %
        self.assertEqual(self.notify.call_count, 2)

    def test_off_is_not_raised(self):
        AlarmSetting.objects.create(site=self.site, alarm_type=0, mode=AlarmSetting.OFF)
        self.assertIsNone(self.raise_high(300.0))
        self.assertFalse(AlarmNotifications.objects.exists())


class VoltageModeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(
            site_name="Volt site", site_type=1, show_voltage_alarms=False,
            r_phase_voltage_threshold_max=240, y_phase_voltage_threshold_max=241,
            b_phase_voltage_threshold_max=242,
        )

    def test_without_setting_the_site_switch_and_fields_decide(self):
        self.assertIsNone(load._voltage_thresholds(self.site, 0))
        self.site.show_voltage_alarms = True
        self.assertEqual(load._voltage_thresholds(self.site, 0), (240, 241, 242))

    def test_auto_manual_off(self):
        setting = AlarmSetting.objects.create(site=self.site, alarm_type=0, mode=AlarmSetting.AUTO)
        self.assertEqual(load._voltage_thresholds(self.site, 0), (253, 253, 253))
        setting.mode, setting.threshold = AlarmSetting.MANUAL, 250
        setting.save()
        self.assertEqual(load._voltage_thresholds(self.site, 0), (250, 250, 250))
        setting.threshold = None
        setting.save()
        self.assertEqual(load._voltage_thresholds(self.site, 0), (240, 241, 242))
        setting.mode = AlarmSetting.OFF
        setting.save()
        self.assertIsNone(load._voltage_thresholds(self.site, 0))

    def test_pf_auto_works_without_site_thresholds(self):
        AlarmSetting.objects.create(site=self.site, alarm_type=2, mode=AlarmSetting.AUTO)
        self.assertEqual(load._pf_thresholds(self.site, {}), (0.9, 0.9, 0.9))


@mock.patch("wareApp.mqtt.services.consumption_alarms.notify")
class ConsumptionModeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Consumption site", site_type=1)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="HB-1", is_active=True)
        self.aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=self.aisle.attached_leg_id, baseline_value=200.0,
            working_hours=24, baseline_from=date(2026, 1, 1),
        )

    def evaluate(self, kwh, day):
        reading = DailySiteReading.objects.create(
            associated_Site=self.site, aisle_group=self.aisle, leg_id=self.aisle.attached_leg_id,
            unit_consumption=kwh, reading_for=day, is_visible=True,
        )
        return evaluate_daily_alarms(self.site, self.aisle, reading)

    def test_bypassed_on_consecutive_days_is_e_mailed_only_when_worse(self, notify):
        self.assertEqual(self.evaluate(220.0, date(2026, 10, 15)), ["Bypassed"])
        self.assertEqual(self.evaluate(225.0, date(2026, 10, 16)), ["Bypassed"])  # +2.3 %
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(self.evaluate(240.0, date(2026, 10, 17)), ["Bypassed"])  # +9 % on 220
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(notify.call_args.args[4], 11)  # alarm type routes the recipients

    def test_a_day_without_the_alarm_clears_it(self, notify):
        self.evaluate(220.0, date(2026, 10, 15))
        self.evaluate(220.0, date(2026, 10, 17))
        self.assertEqual(notify.call_count, 2)

    def test_manual_threshold_and_off(self, notify):
        setting = AlarmSetting.objects.create(
            site=self.site, alarm_type=11, mode=AlarmSetting.MANUAL, threshold=300.0
        )
        self.assertEqual(self.evaluate(250.0, date(2026, 10, 15)), ["High Consumption"])
        setting.mode = AlarmSetting.OFF
        setting.save()
        AlarmSetting.objects.create(site=self.site, alarm_type=7, mode=AlarmSetting.OFF)
        self.assertEqual(self.evaluate(500.0, date(2026, 10, 16)), [])

    def test_low_auto_uses_the_default_percent(self, notify):
        AlarmSetting.objects.create(site=self.site, alarm_type=8, mode=AlarmSetting.AUTO)
        self.assertEqual(self.evaluate(19.0, date(2026, 10, 15)), ["Low Consumption"])  # < 20 = 10 %
        self.assertEqual(self.evaluate(21.0, date(2026, 10, 16)), [])


class GatewayOverheatModeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Hot site", site_type=1)
        notify = mock.patch.object(gateway_overheat, "notify")
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def alert(self, temperature):
        return gateway_overheat.OverheatAlert(self.site.id, "2", temperature, "-", "255")

    def test_manual_threshold_ignores_cooler_alerts(self):
        AlarmSetting.objects.create(site=self.site, alarm_type=13, mode=AlarmSetting.MANUAL, threshold=90)
        self.assertEqual(gateway_overheat.record_overheat(self.alert(87.0)), "below threshold")
        self.assertEqual(gateway_overheat.record_overheat(self.alert(91.0)), "stored")
        self.assertEqual(self.notify.call_count, 1)

    def test_off(self):
        AlarmSetting.objects.create(site=self.site, alarm_type=13, mode=AlarmSetting.OFF)
        self.assertEqual(gateway_overheat.record_overheat(self.alert(95.0)), "off")
        self.assertFalse(AlarmNotifications.objects.exists())
