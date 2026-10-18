"""Recovery status lifecycle (Phase M step M5), against the test database."""

from datetime import date, datetime, timedelta

from django.core.cache import cache
from django.test import override_settings

from wareApp.management.commands.recovery_status_sweep import sweep
from wareApp.models import (
    AisleSyncRecoveryStatus,
    HourlySiteReading,
    RecoveryMonitor,
    SupplyLoadTimeShare,
)
from wareApp.mqtt import (
    daily_consumption_recovery,
    hourly_consumption_recovery,
    load_runtime_recovery,
)
from wareApp.mqtt.services.recovery_status import (
    RecoverySlot,
    RecoveryStatusService,
)
from wareApp.tests.test_mqtt_db_paths import MqttDbTestCase, consumption_message


class RecoveryLifecycleTests(MqttDbTestCase):
    def status(self):
        return AisleSyncRecoveryStatus.objects.get(aisle_group=self.aisle)

    def recover_hours(self, hours_and_values):
        hours = ",".join(f"2026-10-02 {hour:02d}:00:00.000" for hour, _ in hours_and_values)
        values = ",".join(value for _, value in hours_and_values)
        message = (
            f"Aisle_group_id : {self.leg}; Recovery_Hours : {hours},; "
            f"Unit_consumptions : {values},; GW_total_cumulative : 0"
        )
        with self.captureOnCommitCallbacks(execute=True):
            hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
                self.site, self.site.id, "gw-1", message
            )

    def test_gap_creates_one_monitor_and_one_request(self):
        self.hourly(6, 3.0)
        for _ in range(3):
            self.handle(consumption_message(10, 1.5, 0))

        monitor = RecoveryMonitor.objects.get()
        self.assertEqual(monitor.status, "requested")
        self.assertEqual(monitor.recovery_type, "hourly_consumption")
        self.assertEqual(monitor.missing_from, datetime(2026, 10, 2, 7))
        self.assertEqual(monitor.missing_to, datetime(2026, 10, 2, 10))
        self.assertEqual(monitor.expected_slots, 3)
        self.assertEqual(len(self.published), 1)
        status = self.status()
        self.assertEqual(status.sync_status, "recovery_requested")
        self.assertEqual(status.missing_slots, 3)
        self.assertEqual(status.recovery_monitor, monitor)

    def test_complete_recovery_is_verified_and_next_packet_is_healthy(self):
        self.hourly(6, 3.0)
        self.handle(consumption_message(10, 1.5, 0))

        self.recover_hours([(7, "0.5"), (8, "0.6"), (9, "0.7")])

        monitor = RecoveryMonitor.objects.get()
        self.assertEqual(monitor.status, "verified")
        self.assertEqual(monitor.recovered_slots, 3)
        self.assertIsNone(monitor.catch_up_at)
        status = self.status()
        self.assertEqual(status.sync_status, "recovered")
        self.assertFalse(status.has_data_loss)

        self.handle(consumption_message(10, 1.5, 0.7))
        self.assertEqual(self.status().sync_status, "healthy")

    def test_error404_counts_as_resolved_with_data_loss_and_marks_catch_up(self):
        self.hourly(6, 3.0)
        self.handle(consumption_message(10, 1.5, 0))

        self.recover_hours([(7, "ERROR404"), (8, "ERROR404"), (9, "4.2")])

        monitor = RecoveryMonitor.objects.get()
        self.assertEqual(monitor.status, "verified")
        self.assertEqual(monitor.error_slots, 2)
        self.assertEqual(monitor.recovered_slots, 1)
        self.assertEqual(monitor.catch_up_at, datetime(2026, 10, 2, 9))
        self.assertTrue(self.status().has_data_loss)
        # Agreed rule: ERROR404 hours are stored as 0.
        self.assertEqual(
            HourlySiteReading.objects.get(reading_from=datetime(2026, 10, 2, 7)).unit_consumption,
            0.0,
        )

    def test_error404_at_the_end_marks_the_resume_hour_as_catch_up(self):
        self.hourly(6, 3.0)
        self.handle(consumption_message(10, 1.5, 0))

        self.recover_hours([(7, "0.1"), (8, "ERROR404"), (9, "ERROR404")])

        self.assertEqual(
            RecoveryMonitor.objects.get().catch_up_at, datetime(2026, 10, 2, 10)
        )

    def test_partial_recovery_leaves_status_missing(self):
        self.hourly(6, 3.0)
        self.handle(consumption_message(10, 1.5, 0))

        self.recover_hours([(7, "0.5")])

        self.assertEqual(RecoveryMonitor.objects.get().status, "applied")
        status = self.status()
        self.assertEqual(status.sync_status, "missing")
        self.assertEqual(status.missing_slots, 2)

    @override_settings(MQTT_RECOVERY_MAX_ATTEMPTS=3)
    def test_unanswered_request_is_retried_then_failed(self):
        self.hourly(6, 3.0)
        for _ in range(4):
            cache.clear()  # cooldown expired
            self.handle(consumption_message(10, 1.5, 0))

        monitor = RecoveryMonitor.objects.get()
        self.assertEqual(monitor.status, "failed")
        self.assertEqual(monitor.attempt, 3)
        self.assertEqual(len(self.published), 3)
        self.assertEqual(self.status().sync_status, "failed")

        cache.clear()
        self.handle(consumption_message(10, 1.5, 0))
        self.assertEqual(len(self.published), 3)

    def test_failed_request_starts_fresh_after_retry_window(self):
        self.hourly(6, 3.0)
        self.handle(consumption_message(10, 1.5, 0))
        RecoveryMonitor.objects.update(
            status="failed", requested_at=datetime.now() - timedelta(days=1)
        )

        cache.clear()
        self.handle(consumption_message(10, 1.5, 0))

        self.assertEqual(RecoveryMonitor.objects.count(), 2)
        self.assertEqual(len(self.published), 2)

    def test_unsolicited_recovery_is_recorded(self):
        self.recover_hours([(3, "0.5"), (4, "0.6")])

        monitor = RecoveryMonitor.objects.get()
        self.assertEqual(monitor.status, "verified")
        self.assertIsNone(monitor.mqtt_request_topic)
        self.assertEqual(monitor.expected_slots, 2)

    def test_daily_recovery_is_history_only(self):
        self.handle(consumption_message(10, 1.5, 0))
        message = (
            f"Aisle_group_id : {self.leg}; Recovery_Dates : 2026-10-01,; "
            "Unit_consumptions : 12.5,; GW_Total_cumulative : 0"
        )
        with self.captureOnCommitCallbacks(execute=True):
            daily_consumption_recovery.handle_daily_consumption_recovery_message(
                self.site, self.site.id, "gw-1", message
            )

        monitor = RecoveryMonitor.objects.get(recovery_type="daily_consumption")
        self.assertEqual(monitor.status, "applied")
        self.assertEqual(monitor.missing_from, datetime(2026, 10, 1))
        self.assertEqual(self.status().sync_status, "healthy")


class RuntimeRecoveryStatusTests(MqttDbTestCase):
    def supply(self, hour):
        from wareApp.mqtt import supply_time

        with self.captureOnCommitCallbacks(execute=True):
            supply_time.handle_supply_time_message(
                None,
                self.site,
                self.site.id,
                "gw-1",
                f"Source:1,Runtime:300,Time:2026-10-02 {hour:02d}:10:00",
                publish_recovery=self.publish,
            )

    def test_runtime_gap_and_recovery_use_the_source_scope(self):
        SupplyLoadTimeShare.objects.create(
            site=self.site,
            power_source=1,
            hourly_run_time=600,
            reading_from=datetime(2026, 10, 2, 6),
            reading_to=datetime(2026, 10, 2, 6, 59, 59),
        )
        self.supply(9)
        status = AisleSyncRecoveryStatus.objects.get(power_source=1)
        self.assertIsNone(status.aisle_group)
        self.assertEqual(status.sync_status, "recovery_requested")
        self.assertEqual(status.missing_slots, 2)

        message = (
            "Power_source : 1; Recovery_hours : 2026-10-02 07:00:00.000,"
            "2026-10-02 08:00:00.000,; Recovery_load_runtime : 1200,ERROR404,"
        )
        with self.captureOnCommitCallbacks(execute=True):
            load_runtime_recovery.handle_load_runtime_recovery_message(
                self.site, self.site.id, "gw-1", message
            )

        monitor = RecoveryMonitor.objects.get(recovery_type="load_runtime")
        self.assertEqual(monitor.status, "verified")
        self.assertEqual(monitor.error_slots, 1)
        status.refresh_from_db()
        self.assertEqual(status.sync_status, "recovered")
        self.assertTrue(status.has_data_loss)

        self.supply(9)
        status.refresh_from_db()
        self.assertEqual(status.sync_status, "healthy")


class SweepTests(MqttDbTestCase):
    @override_settings(
        MQTT_RECOVERY_REQUEST_COOLDOWN_SECONDS=600,
        MQTT_RECOVERY_MAX_ATTEMPTS=3,
        MQTT_SYNC_LATE_SECONDS=4200,
        MQTT_SYNC_MISSING_SECONDS=7800,
    )
    def test_sweep_times_out_fails_and_marks_late_and_missing(self):
        now = datetime(2026, 10, 2, 12)
        service = RecoveryStatusService(self.site, "gw-1", now=now - timedelta(minutes=20))
        from wareApp.mqtt.services.recovery_status import RecoveryScope

        decision = service.request_recovery(
            RecoveryScope.aisle(self.aisle),
            "hourly_consumption",
            datetime(2026, 10, 2, 6),
            datetime(2026, 10, 2, 10),
            "/t",
            "m",
        )
        failed_monitor = RecoveryMonitor.objects.create(
            site=self.site,
            recovery_type="load_runtime",
            power_source=1,
            status="requested",
            attempt=3,
            missing_from=now,
            requested_at=now - timedelta(minutes=30),
        )
        other = AisleSyncRecoveryStatus.objects.create(
            site=self.site,
            home_gateway_id="gw-2",
            aisle_group=self.aisle,
            sync_status="healthy",
            last_sync_at=now - timedelta(minutes=80),
        )
        gone = AisleSyncRecoveryStatus.objects.create(
            site=self.site,
            home_gateway_id="gw-3",
            aisle_group=self.aisle,
            sync_status="late",
            last_sync_at=now - timedelta(hours=3),
        )

        result = sweep(now=now)

        decision.monitor.refresh_from_db()
        failed_monitor.refresh_from_db()
        other.refresh_from_db()
        gone.refresh_from_db()
        self.assertEqual(decision.monitor.status, "timeout")
        self.assertEqual(failed_monitor.status, "failed")
        self.assertEqual(other.sync_status, "late")
        self.assertEqual(gone.sync_status, "missing")
        self.assertEqual(result["timeout"], 1)
        self.assertEqual(result["failed"], 1)


class CatchUpSlotTests(MqttDbTestCase):
    def test_catch_up_is_first_data_slot_after_last_error(self):
        monitor = RecoveryMonitor(missing_to=datetime(2026, 10, 2, 12))
        slots = [
            RecoverySlot(datetime(2026, 10, 2, 7), False),
            RecoverySlot(datetime(2026, 10, 2, 8), True),
            RecoverySlot(datetime(2026, 10, 2, 9), False),
            RecoverySlot(datetime(2026, 10, 2, 10), True),
            RecoverySlot(datetime(2026, 10, 2, 11), False),
        ]
        self.assertEqual(
            RecoveryStatusService._catch_up_slot(monitor, slots),
            datetime(2026, 10, 2, 11),
        )
        self.assertIsNone(
            RecoveryStatusService._catch_up_slot(monitor, [RecoverySlot(date(2026, 10, 2), False)])
        )
