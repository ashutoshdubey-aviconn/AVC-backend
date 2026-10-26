"""One alarm table: recorder, site alarm APIs and the 0099 data copy."""

import importlib
from datetime import datetime, timedelta
from unittest import mock

from django.apps import apps as django_apps
from django.test import TestCase
from rest_framework.test import APIClient

from wareApp.models import AisleGroup, AlarmNotifications, NewAlarmsNotifications, Site, User
from wareApp.mqtt.services import alarms

TWO_HOURS_AGO = timedelta(hours=2)


class RaisePowerAlarmTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="Power site", site_type=1)
        notify = mock.patch.object(alarms, "notify")
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def raise_pf(self, **kw):
        return alarms.raise_power_alarm(
            self.site, AlarmNotifications.PF_BAD_VALUE, power_source="Mains Supply",
            values={"r_phase": 0.8, "y_phase": 0.95, "b_phase": 0.95},
            repeat_every=timedelta(minutes=30), email=("send", {"x": 1}), **kw,
        )

    def test_first_occurrence_creates_row_and_emails(self):
        alarm = self.raise_pf()
        row = AlarmNotifications.objects.get()
        self.assertEqual(row.pk, alarm.pk)
        self.assertEqual((row.Alarm_type, row.power_source, row.occurrences), (2, "Mains Supply", 1))
        self.assertEqual(float(row.r_phase), 0.8)
        self.assertEqual(row.source, "power")
        self.notify.assert_called_once_with("send", {"x": 1})

    def test_repeat_within_window_is_ignored(self):
        self.raise_pf()
        self.assertIsNone(self.raise_pf())
        self.assertEqual(AlarmNotifications.objects.get().occurrences, 1)
        self.assertEqual(self.notify.call_count, 1)

    def test_repeat_after_window_counts_on_same_row_and_emails(self):
        self.raise_pf()
        AlarmNotifications.objects.update(last_notified_at=datetime.now() - TWO_HOURS_AGO)
        self.raise_pf()
        row = AlarmNotifications.objects.get()
        self.assertEqual(row.occurrences, 2)
        self.assertEqual(self.notify.call_count, 2)

    def test_new_day_starts_a_new_row(self):
        self.raise_pf()
        AlarmNotifications.objects.update(
            created_time=datetime.now() - timedelta(days=1),
            last_notified_at=datetime.now() - timedelta(days=1),
        )
        self.raise_pf()
        self.assertEqual(AlarmNotifications.objects.count(), 2)

    def test_each_source_is_its_own_issue(self):
        self.raise_pf()
        alarms.raise_power_alarm(self.site, 2, power_source="DG_1", repeat_every=timedelta(minutes=30))
        self.assertEqual(AlarmNotifications.objects.count(), 2)

    def test_without_repeat_window_every_call_counts(self):
        for _ in range(3):
            alarms.raise_power_alarm(self.site, AlarmNotifications.FUEL_DRAIN, values={"fuel_level": 400.0})
        row = AlarmNotifications.objects.get()
        self.assertEqual((row.occurrences, row.fuel_level, row.power_source), (3, 400.0, None))


class SiteAlarmApiTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="Mixed site", site_type=1)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="A1")
        AlarmNotifications.objects.create(
            site_id=self.site, Alarm_type=2, Alarm_priority=1, power_source="Mains Supply",
            r_phase=0.8, y_phase=0.9, b_phase=0.9, occurrences=5,
        )
        AlarmNotifications.objects.create(
            site_id=self.site, Alarm_type=11, Alarm_priority=1, aisle_group=self.aisle,
            to_do="Bypassed: consumption=200.00", occurrences=1,
        )
        AlarmNotifications.objects.create(site_id=self.site, Alarm_type=0, Alarm_priority=0, power_source="DG_1")
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="u1", UserType=1))

    def test_summary_lists_every_alarm_type_with_occurrence_counts(self):
        body = self.client.post("/api/alarmList/", {"siteId": self.site.id}, format="json").data
        self.assertEqual(body["total_alarm"], 7)
        self.assertEqual(body["high_priority"], 1)
        self.assertEqual(body["medium_priority"], 6)
        self.assertEqual(body["active_alarms"], 7)
        by_type = {row["alarm_type"]: row for row in body["data"]}
        self.assertEqual(set(by_type), {0, 2, 11})
        self.assertEqual(by_type[2], {"name": "PF Bad Value Alarm", "count": 5, "priority": "Medium", "alarm_type": 2})
        self.assertEqual(by_type[11]["name"], "Bypassed")

    def test_detail_keeps_the_former_keys(self):
        body = self.client.post(
            "/api/alarmListDetail/", {"siteId": self.site.id, "alarm_type": 2}, format="json"
        ).data
        row = body["data"][0]
        for key in ("get_alarm_type_display", "power_source", "get_alarm_priority_display",
                    "r_phase", "y_phase", "b_phase", "fuel_level", "run_hours", "created", "is_active"):
            self.assertIn(key, row)
        self.assertEqual(row["get_alarm_type_display"], "PF Bad Value Alarm")
        self.assertEqual(row["get_alarm_priority_display"], "Medium")
        self.assertEqual(row["occurrences"], 5)

    def test_detail_of_a_consumption_alarm(self):
        body = self.client.post(
            "/api/alarmListDetail/", {"siteId": self.site.id, "alarm_type": 11}, format="json"
        ).data
        self.assertEqual(body["data"][0]["aisle_group"], "A1")
        self.assertTrue(body["data"][0]["issue"].startswith("Bypassed"))


class MigrationCopyTests(TestCase):
    """migration 0099: copy_power_alarms / remove_power_alarms."""

    def setUp(self):
        self.migration = importlib.import_module("wareApp.migrations.0099_alarms_one_table")
        self.site = Site.objects.create(site_name="Old power site", site_type=1)
        when = datetime(2026, 10, 1, 10, 0)
        NewAlarmsNotifications.objects.create(
            site_id=self.site, alarm_type=2, alarm_priority=1, power_source="Mains Supply",
            created=when, r_phase=0.81, y_phase=0.9, b_phase=0.9,
        )
        NewAlarmsNotifications.objects.create(
            site_id=self.site, alarm_type=9, alarm_priority=0, created=None, fuel_level=12.5, is_active=False,
        )

    def test_copy_keeps_type_numbers_and_values_once(self):
        self.migration.copy_power_alarms(django_apps, None)
        self.migration.copy_power_alarms(django_apps, None)  # never copies twice
        rows = {r.Alarm_type: r for r in AlarmNotifications.objects.all()}
        self.assertEqual(set(rows), {2, 9})
        self.assertEqual((rows[2].power_source, float(rows[2].r_phase), rows[2].Alarm_priority), ("Mains Supply", 0.81, 1))
        self.assertEqual(rows[2].created_time, datetime(2026, 10, 1, 10, 0))
        self.assertEqual((rows[9].fuel_level, rows[9].is_active), (12.5, False))
        self.assertEqual(rows[9].created_time, datetime(2026, 10, 1, 10, 0))  # undated: oldest date
        self.migration.remove_power_alarms(django_apps, None)
        self.assertFalse(AlarmNotifications.objects.exists())
