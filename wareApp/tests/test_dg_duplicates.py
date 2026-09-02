from django.test import TestCase
from unittest.mock import patch
from datetime import datetime
import json
from django.db import IntegrityError, transaction

from wareApp.models import Site, DgFuelConsumptionData
from wareApp.dg_fuel import dedupe as dd
import fetch_fuel_data as ff


class DgDuplicateProcessingTests(TestCase):
    def test_reproducible_duplicate_simulation(self):
        """Simulate current ingestion + a legacy processor inserting the same epoch.

        This produces a reproducible duplicate row for the same site/epoch so
        we can write a dedupe/reconciliation fix and lock the regression test.
        """
        site = Site.objects.create(
            site_name="Test Site",
            dg_fuel_system_installed=True,
            partner_dg_fuel_id="VEH1",
        )

        # stub provider response to return a single data point
        js = {"data": [{"timestamp": 1600000000, "fuel_in_liters": 50}]}
        with patch(
            "fetch_fuel_data.request_json", return_value=(js, json.dumps(js), 200)
        ):
            # force deterministic epoch normalization
            with patch(
                "fetch_fuel_data.epoch_ms_from_value", return_value="1600000000000"
            ):
                ff.fetch_real_time_data()

        # ingestion should have created a single row for that epoch
        rows = DgFuelConsumptionData.objects.filter(
            site=site, epoch_time="1600000000000"
        )
        self.assertEqual(rows.count(), 1)

        # the uniqueness constraint should now block the duplicate insert
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DgFuelConsumptionData.objects.create(
                    site=site,
                    vehicle_number="VEH1",
                    fuel_consumption=50,
                    epoch_time="1600000000000",
                    fuel_data_source="legacy",
                    created=datetime.fromtimestamp(1600000000),
                )

        # the dedupe routine should become a no-op once the constraint exists
        removed = dd.dedupe_dg_consumption(site, "VEH1", "1600000000000")
        self.assertEqual(removed, 0)
        rows_after = DgFuelConsumptionData.objects.filter(
            site=site, epoch_time="1600000000000"
        )
        self.assertEqual(rows_after.count(), 1)
