from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db.models import F
from django.core.cache import cache
from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import handlers
from wareApp.mqtt import consumption


class ConsumptionHandlerTests(SimpleTestCase):
    message = (
        "Consumption_time:60,Consumption:1.5,Saving:0,Time:2026-10-02 10,"
        "Leg_Meter_Reading:967_meter,Current_hour_total_consumption:12.5,"
        "Aisle_group:967,GW_total_cumulative:0,Previous_hour_total_consumption:11"
    )

    def setUp(self):
        self.mark_sync_healthy = patch("wareApp.mqtt.consumption.mark_sync_healthy")
        self.mark_recovery_requested = patch(
            "wareApp.mqtt.consumption.RecoveryStatusService"
        )
        self.mark_sync_healthy.start()
        self.mark_recovery_requested.start()
        self.addCleanup(self.mark_sync_healthy.stop)
        self.addCleanup(self.mark_recovery_requested.stop)

    def test_parser_reads_gateway_payload(self):
        values = consumption._parse_consumption_message(self.message)

        self.assertEqual(values["aisle_group_id"], 967)
        self.assertEqual(values["new_unit_consumption"], 1.5)
        self.assertEqual(values["current_hour_consumption"], 12.5)
        self.assertEqual(values["observed_date"], datetime(2026, 10, 2))
        self.assertEqual(values["observed_hour"], 10)

    def test_parser_accepts_gateway_fields_in_any_order(self):
        message = ",".join(reversed(self.message.split(",")))

        values = consumption._parse_consumption_message(message)

        self.assertEqual(values["aisle_group_id"], 967)
        self.assertEqual(values["current_hour_consumption"], 12.5)

    def test_meter_reading_issue_is_stored_and_throttled(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(aisleGroupName="Main Supply")
        message = (
            "ERROR!!! New meter reading for energy of aisle group id 967 "
            "is smaller than previous meter reading."
        )

        with patch(
            "wareApp.mqtt.consumption.AisleGroup.objects.filter",
            return_value=Mock(first=Mock(return_value=aisle_group)),
        ) as aisle_groups, patch(
            "wareApp.mqtt.consumption.cache.add", return_value=True
        ) as cache_add, patch(
            "wareApp.mqtt.consumption.AlarmNotifications.objects.create"
        ) as create, patch("wareApp.mqtt.consumption.notify") as notify:
            consumption._notify_meter_reading_issue(site, 156, "gateway-01", message)

        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1:3], ("Meter Reading Issue", 156))

        aisle_groups.assert_called_once_with(site=site, attached_leg_id="967")
        cache_add.assert_called_once_with(
            "meter-reading-issue-storage:156:gateway-01:967",
            True,
            timeout=consumption.METER_READING_ISSUE_COOLDOWN_SECONDS,
        )
        create.assert_called_once()
        self.assertIs(create.call_args.kwargs["site_id"], site)
        self.assertEqual(create.call_args.kwargs["object_id"], 967)
        self.assertEqual(create.call_args.kwargs["aisle_group"], aisle_group)
        self.assertEqual(create.call_args.kwargs["Alarm_type"], 10)
        self.assertEqual(
            create.call_args.kwargs["to_do"],
            "Gateway gateway-01: lower meter reading reported.",
        )

    def test_meter_reading_issue_does_not_store_a_throttled_duplicate(self):
        site = SimpleNamespace(id=156)
        message = (
            "ERROR!!! New meter reading for energy of aisle group id 967 "
            "is smaller than previous meter reading."
        )

        with patch(
            "wareApp.mqtt.consumption.AisleGroup.objects.filter",
            return_value=Mock(first=Mock(return_value=None)),
        ), patch("wareApp.mqtt.consumption.cache.add", return_value=False), patch(
            "wareApp.mqtt.consumption.AlarmNotifications.objects.create"
        ) as create:
            consumption._notify_meter_reading_issue(site, 156, "gateway-01", message)

        create.assert_not_called()

    def test_daily_consumption_records_high_consumption_at_configured_threshold(self):
        site = SimpleNamespace(
            id=156,
            high_consumption_units=250.0,
            bypass_consumption_units=400.0,
            high_consumption_baseline_percent=None,
            min_threshold_value=None,
        )
        aisle_group = SimpleNamespace(id=967, attached_leg_id="967")
        daily_reading = SimpleNamespace(
            unit_consumption=250.0,
            daily_baseline_value=100.0,
            reading_for=date(2026, 10, 16),
        )
        existing = Mock(exists=Mock(return_value=False))

        with patch(
            "wareApp.mqtt.consumption.AlarmNotifications.objects.filter",
            return_value=existing,
        ), patch(
            "wareApp.mqtt.consumption.AlarmNotifications.objects.create"
        ) as create, patch("wareApp.mqtt.consumption.notify") as notify:
            consumption._consumption_alarms(site, aisle_group, daily_reading)

        self.assertEqual(create.call_args.kwargs["Alarm_type"], 7)
        self.assertEqual(create.call_args.kwargs["object_id"], 967)
        self.assertIn("threshold=250.00", create.call_args.kwargs["to_do"])
        self.assertEqual(notify.call_args.args[1], "High consumption Alarm")

    def test_daily_consumption_records_bypass_instead_of_high_consumption(self):
        site = SimpleNamespace(
            id=156,
            high_consumption_units=250.0,
            bypass_consumption_units=400.0,
            high_consumption_baseline_percent=None,
            min_threshold_value=None,
        )
        aisle_group = SimpleNamespace(id=967, attached_leg_id="967")
        daily_reading = SimpleNamespace(
            unit_consumption=400.0,
            daily_baseline_value=100.0,
            reading_for=date(2026, 10, 16),
        )
        existing = Mock(exists=Mock(return_value=False))

        with patch(
            "wareApp.mqtt.consumption.AlarmNotifications.objects.filter",
            return_value=existing,
        ), patch(
            "wareApp.mqtt.consumption.AlarmNotifications.objects.create"
        ) as create, patch("wareApp.mqtt.consumption.notify") as notify:
            consumption._consumption_alarms(site, aisle_group, daily_reading)

        self.assertEqual(create.call_args.kwargs["Alarm_type"], 11)
        self.assertIn("threshold=400.00", create.call_args.kwargs["to_do"])
        self.assertEqual(notify.call_args.args[1], "Bypassed Alarm")

    def test_hourly_baseline_reads_only_required_values(self):
        cache.clear()
        baselines = Mock()
        baselines.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = (
            48.0,
            24.0,
        )

        with patch("wareApp.mqtt.services.site_cache.SiteBaseline.objects", baselines):
            hourly_baseline, daily_baseline = consumption._hourly_baseline(156, 967)

        self.assertEqual(hourly_baseline, 2.0)
        self.assertEqual(daily_baseline, 48.0)
        baselines.filter.return_value.order_by.return_value.values_list.assert_called_once_with(
            "baseline_value", "working_hours"
        )

    def test_processing_locks_the_aisle_group(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(
            on_sensor_power=False, is_active=False, aisleGroupName="Test Aisle"
        )
        current_hour = Mock(update=Mock(return_value=1))
        hourly_entries = Mock()
        hourly_entries.filter.return_value = current_hour
        daily_entries = Mock(update=Mock(return_value=1))
        aisle_groups = Mock()
        aisle_groups.select_for_update.return_value.filter.return_value.first.return_value = (
            aisle_group
        )

        with patch(
            "wareApp.mqtt.consumption.AisleGroup.objects",
            aisle_groups,
        ), patch(
            "wareApp.mqtt.consumption.HourlySiteReading.objects.filter",
            return_value=hourly_entries,
        ), patch(
            "wareApp.mqtt.consumption.DailySiteReading.objects.filter",
            return_value=daily_entries,
        ):
            consumption.handle_consumption_message.__wrapped__(
                site, 156, "gateway-01", self.message, Mock()
            )

        aisle_groups.select_for_update.assert_called_once_with()
        aisle_groups.select_for_update.return_value.filter.assert_called_once_with(
            site=site, attached_leg_id="967"
        )

    def test_updates_current_hour_and_daily_records(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(
            on_sensor_power=False, is_active=False, aisleGroupName="Test Aisle"
        )
        current_hour = Mock(update=Mock(return_value=1))
        hourly_entries = Mock()
        hourly_entries.filter.return_value = current_hour
        daily_entries = Mock(update=Mock(return_value=1))
        locked_aisle_groups = Mock()
        locked_aisle_groups.filter.return_value.first.return_value = aisle_group

        with patch(
            "wareApp.mqtt.consumption.AisleGroup.objects.select_for_update",
            return_value=locked_aisle_groups,
        ), patch(
            "wareApp.mqtt.consumption.HourlySiteReading.objects.filter",
            return_value=hourly_entries,
        ), patch(
            "wareApp.mqtt.consumption.DailySiteReading.objects.filter",
            return_value=daily_entries,
        ):
            consumption.handle_consumption_message.__wrapped__(
                site, 156, "gateway-01", self.message, Mock()
            )

        current_hour.update.assert_called_once_with(unit_consumption=12.5)
        daily_entries.first.assert_not_called()
        daily_entries.update.assert_called_once_with(
            unit_consumption=F("unit_consumption") + 1.5,
            energy_saved=0.0 - (F("unit_consumption") + 1.5),
            daily_baseline_value=0.0,
        )

    def test_reconciliation_aggregates_the_full_calendar_day(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(
            on_sensor_power=False, is_active=False, aisleGroupName="Test Aisle"
        )
        current_hour = Mock(update=Mock(return_value=0))
        previous_entries = Mock()
        previous_entries.first.return_value = SimpleNamespace(unit_consumption=11)
        hourly_entries = Mock()
        hourly_entries.filter.side_effect = [current_hour, previous_entries]
        daily_entries = Mock()
        daily_entries.first.return_value = Mock(unit_consumption=10)
        hourly_readings = Mock()
        hourly_readings.aggregate.return_value = {"total": 12.5}
        locked_aisle_groups = Mock()
        locked_aisle_groups.filter.return_value.first.return_value = aisle_group

        with patch(
            "wareApp.mqtt.consumption.AisleGroup.objects.select_for_update",
            return_value=locked_aisle_groups,
        ), patch(
            "wareApp.mqtt.consumption.HourlySiteReading.objects.filter",
            side_effect=[hourly_entries, hourly_readings],
        ) as filter_hourly, patch(
            "wareApp.mqtt.consumption.HourlySiteReading.objects.create"
        ), patch(
            "wareApp.mqtt.consumption.DailySiteReading.objects.filter",
            return_value=daily_entries,
        ):
            consumption.handle_consumption_message.__wrapped__(
                site, 156, "gateway-01", self.message, Mock()
            )

        self.assertEqual(
            filter_hourly.call_args_list[1].kwargs["reading_from__gte"],
            datetime(2026, 10, 2),
        )
        self.assertEqual(
            filter_hourly.call_args_list[1].kwargs["reading_from__lt"],
            datetime(2026, 10, 3),
        )

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)
        with patch("wareApp.tasks.site_config.site", return_value=site), patch(
            "wareApp.mqtt.handlers.handle_consumption_message"
        ) as handle:
            tasks.process_consumption_message.run(156, "gateway-01", self.message)

        handle.assert_called_once_with(
            site,
            156,
            "gateway-01",
            self.message,
            publish_recovery=handlers.publish_recovery_request,
        )
