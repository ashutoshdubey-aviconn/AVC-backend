"""Closing resolved alarms (wareApp/mqtt/services/alarm_closer.py)."""

from datetime import datetime, time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from wareApp.models import AlarmNotifications, Site
from wareApp.mqtt.services import alarm_closer, alarms

NOW = datetime(2026, 11, 2, 12, 0)
TODAY = datetime.combine(NOW.date(), time.min)


class AlarmCloserTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Closer site", site_type=1)

    def alarm(self, alarm_type, created, last_seen=None, **extra):
        return AlarmNotifications.objects.create(
            site_id=self.site, Alarm_type=alarm_type, created_time=created, last_seen=last_seen, **extra
        )

    def state(self, alarm):
        alarm.refresh_from_db()
        return alarm.is_active, alarm.off_time

    def test_power_alarm_closes_an_hour_after_it_was_last_seen(self):
        gone = self.alarm(2, NOW - timedelta(hours=3), NOW - timedelta(minutes=61))
        ongoing = self.alarm(0, NOW - timedelta(hours=3), NOW - timedelta(minutes=30))
        old = self.alarm(1, datetime(2023, 10, 26, 16, 51))
        alarm_closer.close_resolved(NOW)
        self.assertEqual(self.state(gone), (False, NOW - timedelta(minutes=61)))
        self.assertEqual(self.state(ongoing)[0], True)
        self.assertEqual(self.state(old), (False, datetime(2023, 10, 26, 16, 51)))

    def test_daily_alarm_stays_one_full_day_then_closes_at_the_end_of_its_day(self):
        yesterday = self.alarm(11, TODAY - timedelta(days=1))
        older = self.alarm(7, TODAY - timedelta(days=2))
        today = self.alarm(17, TODAY)
        legacy = self.alarm(4, datetime(2023, 10, 26, 15, 22))
        alarm_closer.close_resolved(NOW)
        self.assertFalse(self.state(legacy)[0])
        self.assertTrue(self.state(yesterday)[0])
        self.assertTrue(self.state(today)[0])
        self.assertEqual(self.state(older), (False, datetime.combine((TODAY - timedelta(days=2)).date(), time(23, 59, 59))))

    def test_overheat_and_meter_reading_issue(self):
        hot_gone = self.alarm(13, TODAY, NOW - timedelta(hours=3))
        hot_now = self.alarm(13, TODAY, NOW - timedelta(minutes=10))
        meter_gone = self.alarm(10, NOW - timedelta(days=2), NOW - timedelta(hours=25))
        meter_now = self.alarm(10, NOW - timedelta(hours=5), NOW - timedelta(hours=5))
        alarm_closer.close_resolved(NOW)
        self.assertEqual([self.state(a)[0] for a in (hot_gone, hot_now, meter_gone, meter_now)], [False, True, False, True])

    def test_outage_alarms_are_left_to_gateway_health(self):
        outage = self.alarm(15, NOW - timedelta(days=3), NOW - timedelta(days=3))
        alarm_closer.close_resolved(NOW)
        self.assertTrue(self.state(outage)[0])

    def test_dry_run_changes_nothing(self):
        gone = self.alarm(2, NOW - timedelta(hours=3), NOW - timedelta(hours=2))
        counts = alarm_closer.close_resolved(NOW, dry_run=True)
        self.assertEqual(counts["voltage / PF not seen"], 1)
        self.assertTrue(self.state(gone)[0])

    @mock.patch.object(alarms, "notify")
    def test_closed_power_alarm_that_returns_is_a_new_alarm(self, notify):
        first = alarms.raise_power_alarm(self.site, 2, power_source="Mains Supply", severity=0.80,
                                         worse_when_higher=False, email=("send", {}))
        AlarmNotifications.objects.filter(pk=first.pk).update(
            last_seen=datetime.now() - timedelta(hours=2), last_notified_at=datetime.now() - timedelta(hours=2)
        )
        alarm_closer.close_resolved()
        second = alarms.raise_power_alarm(self.site, 2, power_source="Mains Supply", severity=0.80,
                                          worse_when_higher=False, email=("send", {}))
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(AlarmNotifications.objects.filter(is_active=True).count(), 1)
