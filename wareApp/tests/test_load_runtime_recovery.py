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
        self.assertEqual(recovery_hours, ["2026-10-01 10:00:00.000000"])
        self.assertEqual(recovery_values, ["7"])

    def test_parser_keeps_final_value_without_a_trailing_comma(self):
        message = self.message.rstrip(",")

        _, recovery_hours, recovery_values = (
            load_runtime_recovery._parse_load_runtime_recovery_message(message)
        )

        self.assertEqual(recovery_hours, ["2026-10-01 10:00:00.000000"])
        self.assertEqual(recovery_values, ["7"])

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)

        with patch("wareApp.tasks.site_config.site", return_value=site), patch(
            "wareApp.mqtt.handlers.handle_load_runtime_recovery_message"
        ) as handle:
            tasks.process_load_runtime_recovery_message.run(
                156, "gateway-01", self.message
            )

        handle.assert_called_once_with(site, 156, "gateway-01", self.message)
