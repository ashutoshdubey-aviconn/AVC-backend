from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

import fetch_fuel_data
from wareApp.models import AisleGroup, DGFuelAlertsData, DgUnitConsumption, Site


class DgFuelRunnerTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            site_name="DG retry runner test site",
            partner_dg_fuel_id="DG-TEST-01",
            partner_dg_provider="loconav",
        )
        self.aisle_group = AisleGroup.objects.create(
            site=self.site, aisleGroupName="DG", power_source=1
        )
        timestamp = timezone.now() - timedelta(hours=1)
        for _ in range(3):
            DgUnitConsumption.objects.create(
                site=self.site,
                aisle_group=self.aisle_group,
                unit_consumption=1,
                dg_start_date=timestamp,
                dg_end_date=timestamp,
                fetch_fuel_data=True,
                daily_data_status="COMPLETED",
            )

    @patch("fetch_fuel_data.attempt_fetch_for_unit", return_value=False)
    @patch("fetch_fuel_data.RETRY_LIMIT_PER_CYCLE", 2)
    def test_closed_run_retries_are_capped_per_cycle(self, mock_attempt):
        result = fetch_fuel_data.retry_closed_dg_runs()

        self.assertEqual(result, {"attempted": 2, "updated": 0, "failed": 2})
        self.assertEqual(mock_attempt.call_count, 2)

    def _make_provider_site(self, site_name, provider, fuel_id):
        return Site.objects.create(
            site_name=site_name,
            partner_dg_fuel_id=fuel_id,
            partner_dg_provider=provider,
            dg_fuel_system_installed=True,
        )

    @patch("fetch_fuel_data.timezone.localtime")
    @patch("fetch_fuel_data.fetch_loconav_report")
    def test_today_provider_alert_poll_saves_loconav_refuel_without_unit_rows(
        self, mock_report, mock_localtime
    ):
        fixed_now = timezone.make_aware(datetime(2026, 9, 4, 14, 30, 0))
        mock_localtime.return_value = fixed_now
        site = self._make_provider_site(
            "Loconav alert site", "loconav", "DCGenerator-01"
        )
        mock_report.return_value = {
            "status": True,
            "data": {
                "alerts": {
                    "REFUELING_ALERT": [{"timestamp": 1788115579, "value": 40.82}],
                }
            },
        }

        result = fetch_fuel_data.poll_today_provider_alerts()

        self.assertEqual(result["refuels"], 1)
        self.assertEqual(result["thefts"], 0)
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=site,
                vehicle_number="DCGenerator-01",
                alert_name="refuel",
                epoch_time="1788115579000",
            ).exists()
        )
        mock_report.assert_called_once()

    @patch("fetch_fuel_data.timezone.localtime")
    @patch("fetch_fuel_data.fetch_loconav_report")
    def test_today_provider_alert_poll_is_idempotent(self, mock_report, mock_localtime):
        fixed_now = timezone.make_aware(datetime(2026, 9, 4, 14, 30, 0))
        mock_localtime.return_value = fixed_now
        site = self._make_provider_site(
            "Loconav idempotent site", "loconav", "DCGenerator-01"
        )
        mock_report.return_value = {
            "status": True,
            "data": {
                "alerts": {
                    "REFUELING_ALERT": [{"timestamp": 1788115579, "value": 40.82}],
                }
            },
        }

        fetch_fuel_data.poll_today_provider_alerts()
        fetch_fuel_data.poll_today_provider_alerts()

        self.assertEqual(
            DGFuelAlertsData.objects.filter(
                site=site,
                vehicle_number="DCGenerator-01",
                alert_name="refuel",
                epoch_time="1788115579000",
            ).count(),
            1,
        )

    @patch("fetch_fuel_data.timezone.localtime")
    @patch("fetch_fuel_data.fetch_roadcast_report")
    def test_today_provider_alert_poll_saves_roadcast_events(
        self, mock_report, mock_localtime
    ):
        fixed_now = timezone.make_aware(datetime(2026, 9, 4, 14, 30, 0))
        mock_localtime.return_value = fixed_now
        site = self._make_provider_site(
            "Roadcast alert site", "roadcast", "353691840557010"
        )
        mock_report.return_value = {
            "refuels": [{"fuel_liters": 29.39, "epoch_ms": 1788064800000}],
            "thefts": [{"fuel_liters": 1.25, "epoch_ms": 1788072000000}],
        }

        result = fetch_fuel_data.poll_today_provider_alerts()

        self.assertEqual(result["refuels"], 1)
        self.assertEqual(result["thefts"], 1)
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=site,
                vehicle_number="353691840557010",
                alert_name="refuel",
                epoch_time="1788064800000",
            ).exists()
        )
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=site,
                vehicle_number="353691840557010",
                alert_name="theft",
                epoch_time="1788072000000",
            ).exists()
        )

    @patch("fetch_fuel_data.timezone.localtime")
    @patch("fetch_fuel_data.fetch_roadcast_report")
    @patch("fetch_fuel_data.fetch_loconav_report")
    def test_today_provider_alert_poll_continues_after_one_provider_failure(
        self, mock_loconav_report, mock_roadcast_report, mock_localtime
    ):
        fixed_now = timezone.make_aware(datetime(2026, 9, 4, 14, 30, 0))
        mock_localtime.return_value = fixed_now
        loconav_site = self._make_provider_site(
            "Loconav failure site", "loconav", "DCGenerator-01"
        )
        roadcast_site = self._make_provider_site(
            "Roadcast success site", "roadcast", "353691840557010"
        )
        mock_loconav_report.side_effect = RuntimeError("loconav boom")
        mock_roadcast_report.return_value = {
            "refuels": [{"fuel_liters": 29.39, "epoch_ms": 1788064800000}],
            "thefts": [],
        }

        with self.assertLogs("wareApp.dg_fuel.fetch_fuel_data", level="INFO"):
            result = fetch_fuel_data.poll_today_provider_alerts()

        self.assertIn(loconav_site.id, result["failed_site_ids"])
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=roadcast_site,
                vehicle_number="353691840557010",
                alert_name="refuel",
                epoch_time="1788064800000",
            ).exists()
        )

    @patch(
        "fetch_fuel_data.run_dg_fuel_cycle",
        return_value={
            "sites_processed": 1,
            "fuel_levels": {"created": 1, "existing": 0, "failed": 0},
            "refuels": {"created": 1, "existing": 0},
            "thefts": {"created": 0, "existing": 0},
            "dg_units": {"created": 1, "updated": 0, "existing": 0, "unavailable": 0},
            "dg_fuel": {"created": 1, "updated": 0, "existing": 0, "unavailable": 0},
            "dg_per_litre": {"calculated": 1},
            "sites": [],
        },
    )
    def test_run_once_uses_dg_fuel_cycle(self, mock_cycle):
        summary = fetch_fuel_data.run_once()

        self.assertEqual(summary["sites_processed"], 1)
        self.assertEqual(summary["refuels"]["created"], 1)
        mock_cycle.assert_called_once()

    @patch("fetch_fuel_data._log_lines")
    @patch(
        "fetch_fuel_data._fetch_site_dg_fuel",
        return_value=[
            {
                "status": "CREATED",
                "fuel_value": 12.5,
                "database_action": "CREATED",
                "confirmed_zero": False,
                "unit_consumption": 79.69,
            }
        ],
    )
    @patch(
        "fetch_fuel_data.reconcile_daily_unit_consumption",
        return_value={
            "rows": [
                {
                    "aisle_group_id": 1,
                    "status": "CREATED",
                    "unit_id": 11,
                    "daily_reading_value": 79.69,
                    "fetch_fuel_data": True,
                }
            ]
        },
    )
    @patch(
        "fetch_fuel_data._fetch_site_alerts",
        return_value={
            "persisted_refuels": [
                {"fuel_liters": 4.4, "epoch_value": 1788115579000, "created": True}
            ],
            "persisted_thefts": [],
        },
    )
    @patch(
        "fetch_fuel_data._fetch_site_fuel_level",
        return_value={
            "api_status": "STALE",
            "fuel_liters": 268.11,
            "telemetry_state": "STALE",
            "provider_status": "offline",
            "last_update": "2026-09-10T05:07:18.000000+0000",
            "device_name": "153",
            "database_status": "NOT CREATED",
            "created": False,
            "reason": "STALE TELEMETRY",
        },
    )
    def test_run_site_cycle_continues_when_roadcast_telemetry_is_stale(
        self,
        mock_fuel_level,
        mock_alerts,
        mock_reconcile,
        mock_dg_fuel,
        mock_log_lines,
    ):
        site = self._make_provider_site(
            "Roadcast stale site", "roadcast", "353691846234838"
        )
        cycle_start = timezone.make_aware(datetime(2026, 9, 14, 0, 0, 0))
        cycle_end = timezone.make_aware(datetime(2026, 9, 14, 14, 30, 0))

        result = fetch_fuel_data._run_site_cycle(site, cycle_start, cycle_end)

        self.assertFalse(result["stopped"])
        self.assertEqual(result["stop_reason"], None)
        mock_alerts.assert_called_once()
        mock_reconcile.assert_called_once()
        mock_dg_fuel.assert_called_once()
        mock_fuel_level.assert_called_once()
        self.assertTrue(result["refuels"])
