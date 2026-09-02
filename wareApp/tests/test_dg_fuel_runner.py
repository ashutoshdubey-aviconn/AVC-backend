from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

import fetch_fuel_data
from wareApp.models import AisleGroup, DgUnitConsumption, Site


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
            )

    @patch("fetch_fuel_data.attempt_fetch_for_unit", return_value=False)
    @patch("fetch_fuel_data.RETRY_LIMIT_PER_CYCLE", 2)
    def test_closed_run_retries_are_capped_per_cycle(self, mock_attempt):
        result = fetch_fuel_data.retry_closed_dg_runs()

        self.assertEqual(result, {"attempted": 2, "updated": 0, "failed": 2})
        self.assertEqual(mock_attempt.call_count, 2)