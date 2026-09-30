from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import daily_consumption_recovery


class DailyConsumptionRecoveryTests(SimpleTestCase):
    message = (
        "Aisle_group_id : 967; Recovery_Dates : 2026-10-01,; "
        "Unit_consumptions : 12.5,; GW_Total_cumulative : 0"
    )

    def test_parser_reads_gateway_payload(self):
        aisle_group_id, dates, consumptions = (
            daily_consumption_recovery._parse_daily_recovery_message(self.message)
        )

        self.assertEqual(aisle_group_id, "967")
        self.assertEqual(dates, ["2026-10-01", ""])
        self.assertEqual(consumptions, ["12.5", ""])

    def test_updates_only_when_recovered_consumption_is_greater(self):
        aisle_group = SimpleNamespace(is_active=False)
        daily_entries = Mock()
        daily_entries.first.return_value = SimpleNamespace(unit_consumption=10.0)

        with patch(
            "wareApp.mqtt.daily_consumption_recovery.AisleGroup.objects.filter",
            return_value=Mock(first=Mock(return_value=aisle_group)),
        ), patch(
            "wareApp.mqtt.daily_consumption_recovery.DailySiteReading.objects.filter",
            return_value=daily_entries,
        ):
            daily_consumption_recovery.handle_daily_consumption_recovery_message(
                SimpleNamespace(), 156, "gateway-01", self.message
            )

        daily_entries.update.assert_called_once_with(
            unit_consumption=12.5,
            daily_baseline_value=0.0,
            energy_saved=0.0,
        )

    def test_creates_missing_daily_recovery_record(self):
        aisle_group = SimpleNamespace(is_active=False)
        daily_entries = Mock()
        daily_entries.first.return_value = None
        site = SimpleNamespace()

        with patch(
            "wareApp.mqtt.daily_consumption_recovery.AisleGroup.objects.filter",
            return_value=Mock(first=Mock(return_value=aisle_group)),
        ), patch(
            "wareApp.mqtt.daily_consumption_recovery.DailySiteReading.objects.filter",
            return_value=daily_entries,
        ), patch(
            "wareApp.mqtt.daily_consumption_recovery.DailySiteReading.objects.create"
        ) as create:
            daily_consumption_recovery.handle_daily_consumption_recovery_message(
                site, 156, "gateway-01", self.message
            )

        create.assert_called_once_with(
            associated_Site=site,
            aisle_group=aisle_group,
            leg_id="967",
            unit_consumption=12.5,
            daily_baseline_value=0.0,
            energy_saved=0.0,
            reading_for=datetime(2026, 10, 1),
            is_visible=True,
        )

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)

        with patch("wareApp.tasks.Site.objects.get", return_value=site), patch(
            "wareApp.tasks.handle_daily_consumption_recovery_message"
        ) as handle:
            tasks.process_daily_consumption_recovery_message.run(
                156, "gateway-01", self.message
            )

        handle.assert_called_once_with(site, 156, "gateway-01", self.message)
