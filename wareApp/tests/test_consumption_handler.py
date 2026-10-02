from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

    def test_updates_current_hour_and_daily_records(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(on_sensor_power=False, is_active=False)
        current_hour = Mock(update=Mock(return_value=1))
        hourly_entries = Mock()
        hourly_entries.filter.return_value = current_hour
        daily_record = SimpleNamespace(unit_consumption=10)
        daily_entries = Mock(first=Mock(return_value=daily_record))

        with patch(
            "wareApp.mqtt.consumption.AisleGroup.objects.filter",
            return_value=Mock(first=Mock(return_value=aisle_group)),
        ), patch(
            "wareApp.mqtt.consumption.HourlySiteReading.objects.filter",
            return_value=hourly_entries,
        ), patch(
            "wareApp.mqtt.consumption.DailySiteReading.objects.filter",
            return_value=daily_entries,
        ):
            consumption.handle_consumption_message(
                site, 156, "gateway-01", self.message, Mock()
            )

        current_hour.update.assert_called_once_with(unit_consumption=12.5)
        daily_entries.update.assert_called_once_with(
            unit_consumption=11.5,
            energy_saved=-11.5,
            daily_baseline_value=0.0,
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