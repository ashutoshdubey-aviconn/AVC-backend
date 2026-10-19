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

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)

        with patch("wareApp.tasks.site_config.site", return_value=site), patch(
            "wareApp.mqtt.handlers.handle_hourly_consumption_recovery_message"
        ) as handle:
            tasks.process_hourly_consumption_recovery_message.run(
                156, "gateway-01", self.message
            )

        handle.assert_called_once_with(site, 156, "gateway-01", self.message)
