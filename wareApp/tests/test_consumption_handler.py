from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db.models import F
from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import consumption


class ConsumptionHandlerTests(SimpleTestCase):
    message = (
        "Consumption_time:60,Consumption:1.5,Saving:0,Time:2026-10-02 10,"
        "Leg_Meter_Reading:967_meter,Current_hour_total_consumption:12.5,"
        "Aisle_group:967,GW_total_cumulative:0,Previous_hour_total_consumption:11"
    )

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

    def test_processing_locks_the_aisle_group(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(on_sensor_power=False, is_active=False)
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
        aisle_group = SimpleNamespace(on_sensor_power=False, is_active=False)
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
        aisle_group = SimpleNamespace(on_sensor_power=False, is_active=False)
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
        with patch("wareApp.tasks.Site.objects.get", return_value=site), patch(
            "wareApp.tasks.handle_consumption_message"
        ) as handle:
            tasks.process_consumption_message.run(156, "gateway-01", self.message)

        handle.assert_called_once_with(
            site,
            156,
            "gateway-01",
            self.message,
            publish_recovery=tasks._publish_consumption_recovery,
        )
