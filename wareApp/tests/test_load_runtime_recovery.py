from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import load_runtime_recovery


class LoadRuntimeRecoveryTests(SimpleTestCase):
    message = (
        "Power_source : 1; Recovery_hours : 2026-10-01 10:00:00.000000,; "
        "Recovery_load_runtime : 7,"
    )

    def test_parser_reads_gateway_payload(self):
        source, recovery_hours, recovery_values = (
            load_runtime_recovery._parse_load_runtime_recovery_message(self.message)
        )

        self.assertEqual(source, 1)
        self.assertEqual(recovery_hours, ["2026-10-01 10:00:00.000000", ""])
        self.assertEqual(recovery_values, ["7", ""])

    def test_updates_existing_runtime_record(self):
        runtime_entry = Mock()
        runtime_entry.update.return_value = 1
        source_records = Mock()
        source_records.filter.return_value = runtime_entry

        with patch(
            "wareApp.mqtt.load_runtime_recovery.SupplyLoadTimeShare.objects.filter",
            return_value=source_records,
        ):
            load_runtime_recovery.handle_load_runtime_recovery_message(
                SimpleNamespace(), 156, "gateway-01", self.message
            )

        runtime_entry.update.assert_called_once_with(hourly_run_time=7)

    def test_creates_missing_runtime_record(self):
        runtime_entry = Mock()
        runtime_entry.update.return_value = 0
        source_records = Mock()
        source_records.filter.return_value = runtime_entry
        site = SimpleNamespace()

        with patch(
            "wareApp.mqtt.load_runtime_recovery.SupplyLoadTimeShare.objects.filter",
            return_value=source_records,
        ), patch(
            "wareApp.mqtt.load_runtime_recovery.SupplyLoadTimeShare.objects.create"
        ) as create:
            load_runtime_recovery.handle_load_runtime_recovery_message(
                site, 156, "gateway-01", self.message
            )

        create.assert_called_once_with(
            site=site,
            power_source=1,
            hourly_run_time=7,
            reading_from=datetime(2026, 10, 1, 10),
            reading_to=datetime(2026, 10, 1, 10, 59, 59),
        )

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)

        with patch("wareApp.tasks.Site.objects.get", return_value=site), patch(
            "wareApp.tasks.handle_load_runtime_recovery_message"
        ) as handle:
            tasks.process_load_runtime_recovery_message.run(
                156, "gateway-01", self.message
            )

        handle.assert_called_once_with(site, 156, "gateway-01", self.message)
