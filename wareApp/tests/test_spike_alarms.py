"""Consumption Spike alarm (type 17) with its cause (wareApp/mqtt/services/spike_alarms.py)."""

from datetime import date, datetime, time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from wareApp.models import (
    AisleGroup, AlarmNotifications, AlarmSetting, HourlySiteReading, MonitoringMarker, Site, SiteBaseline,
)
from wareApp.mqtt.services import spike_alarms

DAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 18, 0)


@mock.patch("wareApp.mqtt.services.spike_alarms.notify")
class SpikeAlarmTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Spike site", site_type=1, is_live=True)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="F1-C-Section-EL", is_active=True)
        self.aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=self.aisle.attached_leg_id, baseline_value=57.7,
            working_hours=24, baseline_from=date(2026, 1, 1),
        )

    def hours(self, values, day=DAY, first_hour=0):
        for offset, kwh in enumerate(values):
            at = datetime.combine(day, time(first_hour + offset))
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=self.aisle.attached_leg_id,
                unit_consumption=kwh, reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59),
                is_visible=True,
            )

    def alarm(self):
        return AlarmNotifications.objects.get(Alarm_type=17)

    def test_meter_reset_with_a_meter_reading_issue(self, notify):
        self.hours([0.3] * 23, day=date(2026, 10, 29), first_hour=1)
        self.hours([0.3] * 4 + [3290.26] + [0.3] * 7 + [3162.23] + [0.3] * 5)
        AlarmNotifications.objects.create(
            site_id=self.site, aisle_group=self.aisle, Alarm_type=10, object_type=4,
            created_time=datetime.combine(DAY, time(12, 57)), to_do="lower meter reading reported",
        )
        self.assertIn("raised=1", spike_alarms.scan(NOW))
        alarm = self.alarm()
        self.assertEqual((alarm.aisle_group_id, alarm.created_time), (self.aisle.id, datetime.combine(DAY, time.min)))
        self.assertEqual(alarm.Alarm_priority, 0)  # High
        self.assertIn("04:00 3290.26 kWh (meter reset or replaced)", alarm.to_do)
        self.assertEqual(notify.call_args.args[1], "Consumption Spike Alarm")
        self.assertEqual(notify.call_args.args[4], 17)
        details = dict((row[0], row[1]) for row in notify.call_args.args[3])
        self.assertIn("ERROR!!!", details["F1-C-Section-EL 30 Oct 04:00"])

    def test_meter_jump_without_a_meter_issue(self, notify):
        self.hours([0.3] * 23, day=date(2026, 10, 29), first_hour=1)
        self.hours([0.3] * 4 + [500.0] + [0.3] * 5)
        spike_alarms.scan(NOW)
        self.assertIn("meter jump", self.alarm().to_do)

    def test_catch_up_names_the_gateway_alarm_of_the_gap(self, notify):
        self.hours([1.4] * 6, day=date(2026, 10, 29), first_hour=12)  # until 17:00 yesterday
        self.hours([34.23] + [1.4] * 8, first_hour=10)  # today 10:00 carries the gap
        AlarmNotifications.objects.create(
            site_id=self.site, Alarm_type=15, object_type=5, object_id=1, is_active=False,
            created_time=datetime(2026, 10, 29, 19, 0), off_time=datetime(2026, 10, 30, 10, 5),
            to_do="Gateway avc_spike_000001_1: no data and no ping for 1.2 h",
        )
        spike_alarms.scan(NOW)
        alarm = self.alarm()
        self.assertIn("10:00 34.23 kWh (catch-up)", alarm.to_do)
        details = dict((row[0], row[1]) for row in notify.call_args.args[3])
        self.assertIn("16 missing hour(s) 29 Oct 18:00-09:00", details["F1-C-Section-EL 30 Oct 10:00"])
        self.assertIn("Gateway Disconnected: Gateway avc_spike_000001_1", details["F1-C-Section-EL 30 Oct 10:00"])

    def test_catch_up_after_our_own_downtime(self, notify):
        self.hours([1.4] * 6, day=date(2026, 10, 29), first_hour=12)
        self.hours([34.23] + [1.4] * 8, first_hour=10)
        MonitoringMarker.objects.create(name="mqtt_listener_started_at", at=datetime(2026, 10, 30, 9, 50))
        spike_alarms.scan(NOW)
        details = dict((row[0], row[1]) for row in notify.call_args.args[3])
        self.assertIn("our server / listener was down", details["F1-C-Section-EL 30 Oct 10:00"])

    def test_one_alarm_per_day_later_spikes_update_the_text(self, notify):
        self.hours([0.3] * 23, day=date(2026, 10, 29), first_hour=1)
        self.hours([0.3] * 4 + [500.0] + [0.3] * 5)
        spike_alarms.scan(NOW)
        spike_alarms.scan(NOW)
        self.assertEqual(notify.call_count, 1)
        self.hours([600.0], first_hour=10)
        self.assertIn("updated=1", spike_alarms.scan(NOW))
        self.assertIn("10:00 600.00 kWh", self.alarm().to_do)
        self.assertEqual(notify.call_count, 1)

    def test_small_hour_after_a_gap_is_not_a_spike(self, notify):
        # Baseline 57.7 kWh/day -> a catch-up must be above 2 x 2.4 kWh.
        self.hours([0.05] * 6, day=date(2026, 10, 29), first_hour=12)
        self.hours([0.19] + [0.05] * 8, first_hour=10)
        spike_alarms.scan(NOW)
        self.assertFalse(AlarmNotifications.objects.filter(Alarm_type=17).exists())

    def test_one_e_mail_per_site_for_many_aisles(self, notify):
        second = AisleGroup.objects.create(site=self.site, aisleGroupName="F2-C-Section", is_active=True)
        second.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=second.attached_leg_id, baseline_value=57.7,
            working_hours=24, baseline_from=date(2026, 1, 1),
        )
        for aisle in (self.aisle, second):
            self.aisle_backup, self.aisle = self.aisle, aisle
            self.hours([1.4] * 6, day=date(2026, 10, 29), first_hour=12)
            self.hours([34.0] + [1.4] * 8, first_hour=10)
            self.aisle = self.aisle_backup
        self.assertIn("raised=2", spike_alarms.scan(NOW))
        self.assertEqual(AlarmNotifications.objects.filter(Alarm_type=17).count(), 2)
        notify.assert_called_once()
        labels = [row[0] for row in notify.call_args.args[3]]
        self.assertIn("F1-C-Section-EL 30 Oct 10:00", labels)
        self.assertIn("F2-C-Section 30 Oct 10:00", labels)

    def test_normal_day_and_off(self, notify):
        self.hours([0.3] * 23, day=date(2026, 10, 29), first_hour=1)
        self.hours([2.0] * 18)
        spike_alarms.scan(NOW)
        self.assertFalse(AlarmNotifications.objects.filter(Alarm_type=17).exists())
        self.hours([900.0], first_hour=18)
        AlarmSetting.objects.create(site=self.site, alarm_type=17, mode=AlarmSetting.OFF)
        spike_alarms.scan(NOW)
        self.assertFalse(AlarmNotifications.objects.filter(Alarm_type=17).exists())
