from datetime import datetime, timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from wareApp.alarm_feed import active_alarms
from wareApp.models import (
    AisleGroup,
    AisleSyncRecoveryStatus,
    AlarmNotifications,
    HomeGatewayId,
    NewAlarmsNotifications,
    Site,
    User,
)


@override_settings(ALARM_FEED_MAX_AGE_DAYS=0)
class AlarmFeedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = User.objects.create(username="FM-Testing", UserType=4)
        self.site = Site.objects.create(site_name="FM New MCF BGLR Highbay", customer=self.customer, is_live=True)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="D4-OA", is_active=True)
        self.aisle.refresh_from_db()
        HomeGatewayId.objects.create(hgw_id="avc_site_gw_1", connected_to=self.site)
        AisleSyncRecoveryStatus.objects.create(
            site=self.site, home_gateway_id="avc_FMMCF_BGLR_000162_1", aisle_group=self.aisle,
            leg_id=self.aisle.attached_leg_id,
        )
        start = datetime(2026, 10, 20, 0, 7)
        for minutes in (0, 44, 137, 152):  # the same issue stored four times
            AlarmNotifications.objects.create(
                site_id=self.site, aisle_group=self.aisle, object_id=int(self.aisle.attached_leg_id),
                Alarm_type=10, Alarm_priority=1, user_level=2, object_type=4,
                created_time=start + timedelta(minutes=minutes),
                to_do="Gateway avc_FMMCF_BGLR_000162_1: lower meter reading reported.",
            )
        for minutes in (0, 30, 60):
            NewAlarmsNotifications.objects.create(
                site_id=self.site, alarm_type=2, alarm_priority=1, power_source="Mains Supply",
                created=start + timedelta(minutes=minutes), r_phase=0.86, y_phase=0.60, b_phase=0.65,
            )

    def test_one_row_per_issue_from_both_tables(self):
        rows = active_alarms([self.site.id])
        self.assertEqual(len(rows), 2)
        meter = next(r for r in rows if r["alarm_type"] == 10)
        self.assertEqual(meter["alarm"], "Meter Reading Issue")
        self.assertEqual(meter["occurrences"], 4)
        self.assertEqual(meter["created_time"], datetime(2026, 10, 20, 0, 7))
        self.assertEqual(meter["last_seen"], datetime(2026, 10, 20, 2, 39))
        self.assertEqual(meter["aisle_group_name"], "D4-OA")
        self.assertEqual(meter["home_gateway_id"], "avc_FMMCF_BGLR_000162_1")
        self.assertEqual(meter["customer_name"], "FM-Testing")
        self.assertEqual(meter["priority"], "Medium")
        pf = next(r for r in rows if r["source"] == "power")
        self.assertEqual(pf["alarm"], "PF Bad Value Alarm")
        self.assertEqual(pf["occurrences"], 3)
        self.assertEqual(pf["power_source"], "Mains Supply")
        self.assertEqual(pf["home_gateway_id"], "avc_site_gw_1")
        self.assertIn("power factor 0.86/0.6/0.65", pf["issue"])

    def test_alarms_without_time_sort_last(self):
        NewAlarmsNotifications.objects.create(site_id=self.site, alarm_type=0, alarm_priority=0, created=None)
        rows = active_alarms([self.site.id])
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[-1]["last_seen"])

    def test_inactive_alarms_are_left_out(self):
        AlarmNotifications.objects.update(is_active=False)
        NewAlarmsNotifications.objects.update(is_active=False)
        self.assertEqual(active_alarms([self.site.id]), [])

    def test_query_count_does_not_grow_with_rows(self):
        with self.assertNumQueries(7):
            active_alarms([self.site.id])

    def test_type_api_returns_one_row_per_issue(self):
        admin = User.objects.create(username="AVCadmin", UserType=1)
        client = APIClient()
        client.force_authenticate(admin)
        response = client.post("/api/alarmTypeApi/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        [customer] = response.data["data"]
        self.assertEqual(customer["customer_name"], "FM-Testing")
        self.assertEqual(len(customer["alarm_list"]), 2)
        row = customer["alarm_list"][0]
        for key in ("alarm", "Alarm_priority", "site_id__site_name", "created_time", "last_seen",
                    "occurrences", "aisle_group_name", "home_gateway_id", "issue"):
            self.assertIn(key, row)

    def test_priority_api_counts_issues_not_rows(self):
        client = APIClient()
        client.force_authenticate(User.objects.create(username="AVCadmin2", UserType=1))
        response = client.post("/api/alarmapi/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"],
            [[{"Alarm_priority": 1, "site_id__site_name": "FM New MCF BGLR Highbay", "alarm_count": 2}]],
        )


class MeterIssueRepeatTests(TestCase):
    def test_repeat_on_the_same_day_updates_the_active_alarm(self):
        from unittest.mock import patch

        from wareApp.mqtt import consumption

        cache.clear()
        site = Site.objects.create(site_name="Repeat site")
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="D4-OA", is_active=True)
        aisle.refresh_from_db()
        message = (
            f"ERROR!!! New meter reading for energy of aisle group id {aisle.attached_leg_id} "
            "is smaller than previous meter reading."
        )
        with patch("wareApp.mqtt.consumption.notify") as notify:
            consumption._notify_meter_reading_issue(site, site.id, "gw-1", message)
            cache.clear()  # past the 30-minute storage throttle
            consumption._notify_meter_reading_issue(site, site.id, "gw-1", message)

        alarm = AlarmNotifications.objects.get(Alarm_type=10)
        self.assertEqual(alarm.occurrences, 2)
        self.assertIsNotNone(alarm.last_seen)
        notify.assert_called_once()  # e-mailed once, not on the repeat


class AlarmFeedWindowTests(TestCase):
    def test_only_issues_seen_within_the_window_are_listed(self):
        cache.clear()
        site = Site.objects.create(site_name="Window site", is_live=True)
        now = datetime.now()
        # Stale: last seen 40 days ago.
        NewAlarmsNotifications.objects.create(
            site_id=site, alarm_type=0, alarm_priority=0, power_source="Mains Supply",
            created=now - timedelta(days=40),
        )
        # Long-running but still active: started 60 days ago, seen today.
        for days in (60, 0):
            NewAlarmsNotifications.objects.create(
                site_id=site, alarm_type=2, alarm_priority=1, power_source="Mains Supply",
                created=now - timedelta(days=days),
            )

        with override_settings(ALARM_FEED_MAX_AGE_DAYS=30):
            rows = active_alarms([site.id])
        self.assertEqual([r["alarm_type"] for r in rows], [2])
        self.assertEqual(rows[0]["created_time"].date(), (now - timedelta(days=60)).date())
        self.assertEqual(rows[0]["occurrences"], 2)

        with override_settings(ALARM_FEED_MAX_AGE_DAYS=0):
            self.assertEqual(len(active_alarms([site.id])), 2)


@override_settings(ALARM_FEED_MAX_AGE_DAYS=0)
class SnapshotAlarmCountTests(AlarmFeedTests):
    def test_snapshot_counts_the_same_issues_as_the_list(self):
        admin = User.objects.create(username="AVCadmin3", UserType=1)
        client = APIClient()
        client.force_authenticate(admin)
        response = client.post("/api/snapshot/", {"user_id": admin.id}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["alarms"], 2)  # 4 meter rows + 3 PF rows = 2 issues


class SnapshotEnergyTotalsTests(TestCase):
    def setUp(self):
        from datetime import date

        today = date.today()
        self.day = today.replace(day=1)
        for name, consumed, baseline in (("Cust-A", 40.0, 100.0), ("Cust-B", 60.0, 100.0)):
            customer = User.objects.create(username=name, UserType=4)
            site = Site.objects.create(site_name=f"{name} site", customer=customer, is_live=True)
            from wareApp.models import DailySiteReading

            DailySiteReading.objects.create(
                associated_Site=site, leg_id="1", unit_consumption=consumed,
                daily_baseline_value=baseline, energy_saved=baseline - consumed,
                reading_for=self.day, is_visible=True,
            )
        self.admin = User.objects.create(username="AVCadmin4", UserType=1)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.admin)

    def test_totals_are_counted_once(self):
        data = self.client_api.post("/api/snapshot/", {"user_id": self.admin.id}, format="json").data
        self.assertEqual(data["total_unit_consumed"], 100.0)  # 40 + 60, not x2 customers
        self.assertEqual(data["total_energy_saved"], 100.0)  # 60 + 40
        self.assertEqual(data["total_saved_percentage"], "50.0")  # 100 / 200

    def test_date_range_variant_works(self):
        day = self.day.strftime("%Y/%m/%d")
        response = self.client_api.post(
            "/api/snapshot/", {"user_id": self.admin.id, "start_date": day, "end_date": day}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_unit_consumed"], 100.0)
