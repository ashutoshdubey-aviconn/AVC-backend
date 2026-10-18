"""Database-backed tests for the MQTT write paths (Phase M step M4).

These run the real handlers against the test database, check the rows they
leave behind, and pin the number of queries per path so later changes cannot
silently add database round trips.
"""

from datetime import date, datetime

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from wareApp.models import (
    AisleGroup,
    AisleSyncRecoveryStatus,
    DailySiteReading,
    HourlySiteReading,
    Site,
    SiteBaseline,
    SupplyLoadTimeShare,
)
from wareApp.mqtt import (
    consumption,
    daily_consumption_recovery,
    hourly_consumption_recovery,
    load_runtime_recovery,
    supply_time,
    sync_status,
)
from wareApp.mqtt.services import site_cache


def consumption_message(hour, current_total, previous_total, new_units=1.5, leg="{leg}"):
    return (
        f"Consumption_time:60,Consumption:{new_units},Saving:0,Time:2026-10-02 {hour},"
        f"Leg_Meter_Reading:{leg}_meter,Current_hour_total_consumption:{current_total},"
        f"Aisle_group:{leg},GW_total_cumulative:0,"
        f"Previous_hour_total_consumption:{previous_total}"
    )


class MqttDbTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Test site", site_type=1)
        self.aisle = AisleGroup.objects.create(
            site=self.site, aisleGroupName="RPC-F1", is_active=True
        )
        # A post_save signal sets attached_leg_id to the aisle group's id.
        self.aisle.refresh_from_db()
        self.leg = self.aisle.attached_leg_id
        SiteBaseline.objects.create(
            associated_site_id=self.site,
            leg_id=self.leg,
            baseline_value=48.0,
            working_hours=24,
        )
        self.published = []

    def publish(self, topic, message):
        self.published.append((topic, message))

    def handle(self, message):
        # Run on_commit callbacks (cache refresh, publish) as production would.
        with self.captureOnCommitCallbacks(execute=True):
            consumption.handle_consumption_message(
                self.site,
                self.site.id,
                "gw-1",
                message.replace("{leg}", self.leg),
                self.publish,
            )

    def hourly(self, hour, units, day=2):
        return HourlySiteReading.objects.create(
            associated_Site=self.site,
            aisle_group=self.aisle,
            leg_id=self.leg,
            unit_consumption=units,
            reading_from=datetime(2026, 10, day, hour),
            reading_to=datetime(2026, 10, day, hour, 59, 59),
            is_visible=True,
        )

    def daily(self, units, day=2):
        return DailySiteReading.objects.create(
            associated_Site=self.site,
            aisle_group=self.aisle,
            leg_id=self.leg,
            unit_consumption=units,
            reading_for=date(2026, 10, day),
            is_visible=True,
        )


class ConsumptionPathTests(MqttDbTestCase):
    def test_first_ever_packet_creates_hourly_and_daily_rows(self):
        self.handle(consumption_message(10, 1.5, 0))

        hourly = HourlySiteReading.objects.get()
        self.assertEqual(hourly.unit_consumption, 1.5)
        self.assertEqual(hourly.hourly_baseline_value, 2.0)
        self.assertEqual(DailySiteReading.objects.get().daily_baseline_value, 48.0)
        self.assertEqual(self.published, [])
        status = AisleSyncRecoveryStatus.objects.get()
        self.assertEqual(status.sync_status, "healthy")

    def test_current_hour_packet_updates_hour_and_adds_to_day(self):
        self.hourly(10, 5.0)
        self.daily(5.0)

        self.handle(consumption_message(10, 6.5, 0))

        self.assertEqual(HourlySiteReading.objects.get().unit_consumption, 6.5)
        daily = DailySiteReading.objects.get()
        self.assertEqual(daily.unit_consumption, 6.5)
        self.assertEqual(daily.energy_saved, 48.0 - 6.5)

    def test_new_hour_syncs_previous_hour_and_resums_day(self):
        self.hourly(9, 4.0)
        self.hourly(8, 3.0)
        self.daily(99.0)

        self.handle(consumption_message(10, 1.5, 5.0))

        previous = HourlySiteReading.objects.get(reading_from=datetime(2026, 10, 2, 9))
        self.assertEqual(previous.unit_consumption, 5.0)
        self.assertEqual(previous.energy_saved, 2.0 - 5.0)
        # Day re-summed from hourly rows (3 + 5) before the new hour's units.
        self.assertEqual(DailySiteReading.objects.get().unit_consumption, 3.0 + 5.0 + 1.5)
        self.assertTrue(
            HourlySiteReading.objects.filter(reading_from=datetime(2026, 10, 2, 10)).exists()
        )

    def test_gap_requests_recovery_once_per_cooldown_and_drops_packets(self):
        self.hourly(6, 3.0)
        self.daily(3.0)

        for _ in range(3):
            self.handle(consumption_message(10, 1.5, 0))

        self.assertEqual(len(self.published), 1)
        topic, message = self.published[0]
        self.assertEqual(topic, f"/Acclivate/iOmniControl/{self.site.id}/gw-1/in/sync/consumption/state")
        self.assertIn("Last_Synced_hour :2026-10-02 06:59:59", message)
        # Agreed behaviour: packets during a gap are not stored.
        self.assertEqual(HourlySiteReading.objects.count(), 1)
        self.assertEqual(DailySiteReading.objects.get().unit_consumption, 3.0)
        self.assertEqual(
            AisleSyncRecoveryStatus.objects.get().sync_status, "recovery_requested"
        )

    def test_energy_saving_site_caps_glitch_values(self):
        self.site.site_type = 2
        self.site.save()

        self.handle(consumption_message(10, 15000, 0, new_units=12000))

        self.assertEqual(HourlySiteReading.objects.get().unit_consumption, 0.0)


class ConsumptionQueryBudgetTests(MqttDbTestCase):
    """Round trips per packet (TestCase counts the transaction as SAVEPOINTs)."""

    def count_queries(self, message):
        with CaptureQueriesContext(connection) as queries:
            self.handle(message)
        self.last_queries = [query["sql"] for query in queries]
        return len(queries)

    def test_current_hour_packet_query_budget(self):
        self.hourly(10, 5.0)
        self.daily(5.0)
        self.handle(consumption_message(10, 5.5, 0))  # warms caches + sync status

        # transaction start/end + lock aisle, update hour, update day
        # (site and baseline cached, sync status unchanged). Was ~11.
        count = self.count_queries(consumption_message(10, 6.0, 0))
        self.assertLessEqual(count, 5, self.last_queries)

    def test_repeat_gap_packet_query_budget(self):
        self.hourly(6, 3.0)
        self.handle(consumption_message(10, 1.5, 0))

        # transaction start/end + lock aisle, update hour (0 rows),
        # previous-hour lookup; no publish, no status write. Was ~10.
        count = self.count_queries(consumption_message(10, 1.6, 0))
        self.assertLessEqual(count, 5, self.last_queries)


class SyncStatusWriteTests(MqttDbTestCase):
    def mark_healthy(self, observed):
        with self.captureOnCommitCallbacks(execute=True):
            return sync_status.mark_sync_healthy(self.site, "gw-1", self.aisle, observed)

    def test_healthy_is_written_once_per_hour(self):
        observed = datetime(2026, 10, 2, 10)
        self.assertTrue(self.mark_healthy(observed))
        self.assertFalse(self.mark_healthy(observed.replace(minute=30)))
        self.assertTrue(self.mark_healthy(datetime(2026, 10, 2, 11)))
        self.assertEqual(AisleSyncRecoveryStatus.objects.count(), 1)

    def test_transition_clears_cached_healthy_state(self):
        observed = datetime(2026, 10, 2, 10)
        self.mark_healthy(observed)
        with self.captureOnCommitCallbacks(execute=True):
            sync_status.mark_recovery_requested(
                self.site, "gw-1", self.aisle, observed, observed
            )

        self.assertTrue(self.mark_healthy(observed))
        self.assertEqual(AisleSyncRecoveryStatus.objects.get().sync_status, "healthy")


class RecoveryWriteTests(MqttDbTestCase):
    def hourly_message(self, hours, values):
        return (
            f"Aisle_group_id : {self.leg}; Recovery_Hours : {','.join(hours)},; "
            f"Unit_consumptions : {','.join(values)},; GW_total_cumulative : 0"
        )

    def test_hourly_recovery_updates_creates_and_keeps_error404_as_zero(self):
        self.hourly(1, 9.0)
        hours = [f"2026-10-02 {hour:02d}:00:00.000" for hour in range(1, 4)]
        message = self.hourly_message(hours, ["0.5", "ERROR404", "0.7"])

        hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
            self.site, self.site.id, "gw-1", message
        )

        values = dict(
            HourlySiteReading.objects.values_list("reading_from", "unit_consumption")
        )
        self.assertEqual(values[datetime(2026, 10, 2, 1)], 0.5)
        self.assertEqual(values[datetime(2026, 10, 2, 2)], 0.0)
        self.assertEqual(values[datetime(2026, 10, 2, 3)], 0.7)
        self.assertEqual(AisleSyncRecoveryStatus.objects.get().sync_status, "recovered")

    def test_hourly_recovery_of_38_hours_is_a_handful_of_queries(self):
        hours = [
            f"2026-10-{1 + hour // 24:02d} {hour % 24:02d}:00:00.000" for hour in range(38)
        ]
        message = self.hourly_message(hours, ["0.09"] * 38)

        with CaptureQueriesContext(connection) as queries:
            hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
                self.site, self.site.id, "gw-1", message
            )

        self.assertEqual(HourlySiteReading.objects.count(), 38)
        # aisle lookup + status writes + 1 select + 1 bulk insert (+ savepoints)
        self.assertLessEqual(len(queries), 12)

    def test_daily_recovery_never_lowers_a_known_value(self):
        self.daily(20.0, day=1)
        message = (
            f"Aisle_group_id : {self.leg}; Recovery_Dates : 2026-10-01,2026-10-02,; "
            "Unit_consumptions : 12.5,30.0,; GW_Total_cumulative : 0"
        )

        daily_consumption_recovery.handle_daily_consumption_recovery_message(
            self.site, self.site.id, "gw-1", message
        )

        values = dict(DailySiteReading.objects.values_list("reading_for", "unit_consumption"))
        self.assertEqual(values[date(2026, 10, 1)], 20.0)
        self.assertEqual(values[date(2026, 10, 2)], 30.0)

    def test_daily_recovery_raises_lower_value(self):
        self.daily(10.0, day=1)
        message = (
            f"Aisle_group_id : {self.leg}; Recovery_Dates : 2026-10-01,; "
            "Unit_consumptions : 12.5,; GW_Total_cumulative : 0"
        )

        daily_consumption_recovery.handle_daily_consumption_recovery_message(
            self.site, self.site.id, "gw-1", message
        )

        reading = DailySiteReading.objects.get()
        self.assertEqual(reading.unit_consumption, 12.5)
        self.assertEqual(reading.daily_baseline_value, 48.0)
        self.assertEqual(reading.energy_saved, 48.0 - 12.5)

    def test_runtime_recovery_updates_and_creates(self):
        SupplyLoadTimeShare.objects.create(
            site=self.site,
            power_source=1,
            hourly_run_time=99,
            reading_from=datetime(2026, 10, 2, 1),
            reading_to=datetime(2026, 10, 2, 1, 59, 59),
        )
        message = (
            "Power_source : 1; Recovery_hours : 2026-10-02 01:00:00.000,"
            "2026-10-02 02:00:00.000,; Recovery_load_runtime : ERROR404,1200,"
        )

        load_runtime_recovery.handle_load_runtime_recovery_message(
            self.site, self.site.id, "gw-1", message
        )

        values = dict(SupplyLoadTimeShare.objects.values_list("reading_from", "hourly_run_time"))
        self.assertEqual(values[datetime(2026, 10, 2, 1)], 0)
        self.assertEqual(values[datetime(2026, 10, 2, 2)], 1200)

    def test_failed_recovery_leaves_no_partial_rows(self):
        message = self.hourly_message(["2026-10-02 01:00:00.000", "not-a-date"], ["1", "2"])

        hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
            self.site, self.site.id, "gw-1", message
        )

        self.assertEqual(HourlySiteReading.objects.count(), 0)


class SiteConfigCacheTests(MqttDbTestCase):
    def test_site_is_cached_and_invalidated_on_save(self):
        site_cache.site(self.site.id)
        with CaptureQueriesContext(connection) as queries:
            site_cache.site(self.site.id)
        self.assertEqual(len(queries), 0)

        self.site.site_name = "Renamed"
        self.site.save()
        self.assertEqual(site_cache.site(self.site.id).site_name, "Renamed")

    def test_baseline_cache_is_invalidated_when_baseline_changes(self):
        self.assertEqual(site_cache.latest_baseline(self.site.id, self.leg), (48.0, 24.0))
        baseline = SiteBaseline.objects.get()
        baseline.baseline_value = 72.0
        baseline.save()
        self.assertEqual(site_cache.latest_baseline(self.site.id, self.leg), (72.0, 24.0))

    def test_unknown_site_raises(self):
        with self.assertRaises(Site.DoesNotExist):
            site_cache.site(999999)
        with self.assertRaises(Site.DoesNotExist):
            site_cache.site(999999)


class SupplyTimePathTests(MqttDbTestCase):
    def supply(self, hour, runtime=300):
        with self.captureOnCommitCallbacks(execute=True):
            supply_time.handle_supply_time_message(
                None,
                self.site,
                self.site.id,
                "gw-1",
                f"Source:1,Runtime:{runtime},Time:2026-10-02 {hour:02d}:10:00",
                publish_recovery=self.publish,
            )

    def runtime_row(self, hour, runtime=600):
        return SupplyLoadTimeShare.objects.create(
            site=self.site,
            power_source=1,
            hourly_run_time=runtime,
            reading_from=datetime(2026, 10, 2, hour),
            reading_to=datetime(2026, 10, 2, hour, 59, 59),
        )

    def test_new_hour_after_previous_hour_creates_row_without_extra_query(self):
        self.runtime_row(9)
        with CaptureQueriesContext(connection) as queries:
            self.supply(10)

        self.assertEqual(SupplyLoadTimeShare.objects.count(), 2)
        self.assertFalse(any("EXISTS" in q["sql"].upper() for q in queries))

    def test_gap_requests_runtime_recovery_once(self):
        self.runtime_row(6)

        self.supply(10)
        self.supply(10)

        self.assertEqual(len(self.published), 1)
        self.assertIn("/in/sync/loadTime/state", self.published[0][0])
        self.assertEqual(SupplyLoadTimeShare.objects.count(), 1)


class DailyAlarmDedupeTests(MqttDbTestCase):
    def test_high_consumption_alarm_is_stored_once_per_day(self):
        from wareApp.models import AlarmNotifications

        self.site.high_consumption_units = 10.0
        reading = self.daily(20.0)
        consumption._consumption_alarms(self.site, self.aisle, reading)
        consumption._consumption_alarms(self.site, self.aisle, reading)

        self.assertEqual(AlarmNotifications.objects.filter(Alarm_type=7).count(), 1)

    def test_meter_reading_issue_is_stored(self):
        from wareApp.models import AlarmNotifications

        consumption._notify_meter_reading_issue(
            self.site,
            self.site.id,
            "gw-1",
            f"ERROR!!! New meter reading for energy of aisle group id {self.leg} "
            "is smaller than previous meter reading.",
        )

        self.assertEqual(AlarmNotifications.objects.filter(Alarm_type=10).count(), 1)
