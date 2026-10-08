from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import hourly_consumption_recovery


class HourlyConsumptionRecoveryTests(SimpleTestCase):
    message = (
        "Aisle_group_id : 967; Recovery_Hours : 2026-10-02 10:15:00.000000,; "
        "Unit_consumptions : 12.5,; GW_total_cumulative : 0"
    )

    def test_parser_reads_gateway_payload(self):
        aisle_group_id, hours, consumptions = (
            hourly_consumption_recovery._parse_hourly_recovery_message(self.message)
        )

        self.assertEqual(aisle_group_id, "967")
        self.assertEqual(hours, ["2026-10-02 10:15:00.000000"])
        self.assertEqual(consumptions, ["12.5"])

    def test_parser_keeps_final_value_without_a_trailing_comma(self):
        message = self.message.replace("12.5,;", "12.5;")

        _, hours, consumptions = (
            hourly_consumption_recovery._parse_hourly_recovery_message(message)
        )

        self.assertEqual(hours, ["2026-10-02 10:15:00.000000"])
        self.assertEqual(consumptions, ["12.5"])

    def test_updates_existing_hourly_recovery_record(self):
        aisle_group = SimpleNamespace(is_active=False)
        hourly_entries = Mock()
        hourly_entries.update.return_value = 1

        with patch(
            "wareApp.mqtt.hourly_consumption_recovery.AisleGroup.objects.filter",
            return_value=Mock(first=Mock(return_value=aisle_group)),
        ), patch(
            "wareApp.mqtt.hourly_consumption_recovery.HourlySiteReading.objects.filter",
            return_value=hourly_entries,
        ):
            hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
                SimpleNamespace(), 156, "gateway-01", self.message
            )

        hourly_entries.update.assert_called_once_with(
            unit_consumption=12.5,
            hourly_baseline_value=0.0,
            energy_saved=0.0,
        )

    def test_creates_missing_hourly_recovery_record(self):
        aisle_group = SimpleNamespace(is_active=False)
        hourly_entries = Mock()
        hourly_entries.update.return_value = 0
        site = SimpleNamespace()

        with patch(
            "wareApp.mqtt.hourly_consumption_recovery.AisleGroup.objects.filter",
            return_value=Mock(first=Mock(return_value=aisle_group)),
        ), patch(
            "wareApp.mqtt.hourly_consumption_recovery.HourlySiteReading.objects.filter",
            return_value=hourly_entries,
        ), patch(
            "wareApp.mqtt.hourly_consumption_recovery.HourlySiteReading.objects.create"
        ) as create:
            hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
                site, 156, "gateway-01", self.message
            )

        create.assert_called_once_with(
            associated_Site=site,
            aisle_group=aisle_group,
            leg_id="967",
            unit_consumption=12.5,
            hourly_baseline_value=0.0,
            energy_saved=0.0,
            reading_from=datetime(2026, 10, 2, 10),
            reading_to=datetime(2026, 10, 2, 10, 59, 59),
            is_visible=True,
        )

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)

        with patch("wareApp.tasks.Site.objects.get", return_value=site), patch(
            "wareApp.tasks.handle_hourly_consumption_recovery_message"
        ) as handle:
            tasks.process_hourly_consumption_recovery_message.run(
                156, "gateway-01", self.message
            )

        handle.assert_called_once_with(site, 156, "gateway-01", self.message)
