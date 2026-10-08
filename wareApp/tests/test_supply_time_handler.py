from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db.models import F
from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import supply_time


class SupplyTimeHandlerTests(SimpleTestCase):
    message = "Source:1,RunTime:12,Z:0,Time:2026-10-01 10:15:00.000000"

    def test_parser_reads_gateway_payload(self):
        source, run_time, observed_at = supply_time._parse_supply_time_message(
            f"b'{self.message}'"
        )

        self.assertEqual(source, 1)
        self.assertEqual(run_time, 12.0)
        self.assertEqual(observed_at, datetime(2026, 10, 1, 10, 15))

    def test_updates_existing_hourly_runtime(self):
        current_hour = Mock()
        current_hour.update.return_value = 1
        run_time = Mock()
        run_time.filter.return_value = current_hour

        with patch(
            "wareApp.mqtt.supply_time.SupplyLoadTimeShare.objects.filter",
            return_value=run_time,
        ):
            supply_time.handle_supply_time_message(
                Mock(), SimpleNamespace(), 156, "gateway-01", self.message
            )

        current_hour.update.assert_called_once_with(
            hourly_run_time=F("hourly_run_time") + 12.0
        )

    def test_creates_first_runtime_record(self):
        current_hour = Mock()
        current_hour.update.return_value = 0
        previous_hour = Mock()
        run_time = Mock()
        run_time.filter.side_effect = [current_hour, previous_hour]
        run_time.order_by.return_value.first.return_value = None
        site = SimpleNamespace()

        with patch(
            "wareApp.mqtt.supply_time.SupplyLoadTimeShare.objects.filter",
            return_value=run_time,
        ), patch(
            "wareApp.mqtt.supply_time.SupplyLoadTimeShare.objects.create"
        ) as create:
            supply_time.handle_supply_time_message(
                Mock(), site, 156, "gateway-01", self.message
            )

        create.assert_called_once_with(
            site=site,
            power_source=1,
            hourly_run_time=12.0,
            reading_from=datetime(2026, 10, 1, 10),
            reading_to=datetime(2026, 10, 1, 10, 59, 59),
        )

    def test_requests_recovery_when_previous_hour_is_missing(self):
        current_hour = Mock()
        current_hour.update.return_value = 0
        previous_hour = Mock()
        previous_hour.exists.return_value = False
        run_time = Mock()
        run_time.filter.side_effect = [current_hour, previous_hour]
        run_time.order_by.return_value.first.return_value = SimpleNamespace(
            reading_from=datetime(2026, 10, 1, 8)
        )
        client = Mock()

        with patch(
            "wareApp.mqtt.supply_time.SupplyLoadTimeShare.objects.filter",
            return_value=run_time,
        ), patch("wareApp.mqtt.supply_time._update_monthly_share_if_due"):
            supply_time.handle_supply_time_message(
                client, SimpleNamespace(), 156, "gateway-01", self.message
            )

        client.publish.assert_called_once()
        self.assertEqual(
            client.publish.call_args.args[0],
            "/Acclivate/iOmniControl/156/gateway-01/in/sync/loadTime/state",
        )

    def test_monthly_share_uses_previous_month_grouped_totals(self):
        site = SimpleNamespace()
        last_runtime_entry = SimpleNamespace(reading_from=datetime(2026, 10, 31, 23))
        grouped_totals = [
            {"power_source": 1, "total_runtime": 30},
            {"power_source": 2, "total_runtime": 70},
        ]
        values = Mock()
        values.annotate.return_value = grouped_totals
        entries = Mock()
        entries.values.return_value = values
        monthly_share = Mock()
        monthly_share.update.return_value = 0

        with patch(
            "wareApp.mqtt.supply_time.SupplyLoadTimeShare.objects.filter",
            return_value=entries,
        ) as filter_entries, patch(
            "wareApp.mqtt.supply_time.MonthlyLoadSharePercentage.objects.filter",
            return_value=monthly_share,
        ) as filter_monthly_share, patch(
            "wareApp.mqtt.supply_time.MonthlyLoadSharePercentage.objects.create"
        ) as create:
            supply_time._update_monthly_share_if_due(
                site, 156, last_runtime_entry, datetime(2026, 11, 1, 3)
            )

        filter_entries.assert_called_once_with(
            site=156,
            reading_from__gte=datetime(2026, 10, 1),
            reading_from__lt=datetime(2026, 11, 1),
        )
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].kwargs["power_source"], 1)
        self.assertEqual(
            create.call_args_list[0].kwargs["monthly_time_based_percentage"], 30
        )
        self.assertEqual(create.call_args_list[1].kwargs["power_source"], 2)
        self.assertEqual(
            create.call_args_list[1].kwargs["monthly_time_based_percentage"], 70
        )
        self.assertEqual(filter_monthly_share.call_count, 2)

    def test_monthly_share_updates_existing_record(self):
        site = SimpleNamespace()
        last_runtime_entry = SimpleNamespace(reading_from=datetime(2026, 10, 31, 23))
        values = Mock()
        values.annotate.return_value = [{"power_source": 1, "total_runtime": 10}]
        entries = Mock()
        entries.values.return_value = values
        monthly_share = Mock()
        monthly_share.update.return_value = 1

        with patch(
            "wareApp.mqtt.supply_time.SupplyLoadTimeShare.objects.filter",
            return_value=entries,
        ), patch(
            "wareApp.mqtt.supply_time.MonthlyLoadSharePercentage.objects.filter",
            return_value=monthly_share,
        ), patch(
            "wareApp.mqtt.supply_time.MonthlyLoadSharePercentage.objects.create"
        ) as create:
            supply_time._update_monthly_share_if_due(
                site, 156, last_runtime_entry, datetime(2026, 11, 1, 3)
            )

        monthly_share.update.assert_called_once_with(monthly_time_based_percentage=100)
        create.assert_not_called()

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)

        with patch("wareApp.tasks.Site.objects.get", return_value=site), patch(
            "wareApp.tasks.handle_supply_time_message"
        ) as handle:
            tasks.process_supply_time_message.run(156, "gateway-01", self.message)

        handle.assert_called_once_with(
            None,
            site,
            156,
            "gateway-01",
            self.message,
            publish_recovery=tasks._publish_supply_time_recovery,
        )
