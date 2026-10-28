from django.test import TestCase

from wareApp.dg_fuel.ingestion import record_fuel_alert, record_fuel_level
from wareApp.models import DGFuelAlertsData, DgFuelConsumptionData, Site


class DgFuelIngestionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="DG fuel ingestion test site")

    def test_record_fuel_level_is_idempotent_for_normalized_epoch(self):
        first, first_created = record_fuel_level(
            site=self.site,
            vehicle_number="PBDN450",
            fuel_liters="710.0",
            epoch_value=1771733745000,
            source="loconav",
        )
        second, second_created = record_fuel_level(
            site=self.site,
            vehicle_number="PBDN450",
            fuel_liters=710,
            epoch_value="1771733745000",
            source="loconav",
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            DgFuelConsumptionData.objects.filter(site=self.site).count(), 1
        )

    def test_record_fuel_alert_normalizes_seconds_and_is_idempotent(self):
        first, first_created = record_fuel_alert(
            site=self.site,
            vehicle_number="DCGenerator-01",
            alert_name="refuel",
            fuel_liters="12.5",
            epoch_value=1788115579,
        )
        second, second_created = record_fuel_alert(
            site=self.site,
            vehicle_number="DCGenerator-01",
            alert_name="refuel",
            fuel_liters=12.5,
            epoch_value=1788115579000,
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.epoch_time, "1788115579000")
        self.assertEqual(DGFuelAlertsData.objects.filter(site=self.site).count(), 1)

    def test_record_fuel_alert_handles_theft_events(self):
        first, first_created = record_fuel_alert(
            site=self.site,
            vehicle_number="DCGenerator-01",
            alert_name="theft",
            fuel_liters="1.2",
            epoch_value="1788072000000",
        )
        second, second_created = record_fuel_alert(
            site=self.site,
            vehicle_number="DCGenerator-01",
            alert_name="theft",
            fuel_liters=1.2,
            epoch_value=1788072000,
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.epoch_time, "1788072000000")
        self.assertEqual(DGFuelAlertsData.objects.filter(site=self.site).count(), 1)

    def test_rejects_invalid_level_and_alert_inputs(self):
        with self.assertRaises(ValueError):
            record_fuel_level(
                site=self.site,
                vehicle_number="PBDN450",
                fuel_liters="not-a-number",
                epoch_value=1788115579000,
                source="loconav",
            )
        with self.assertRaises(ValueError):
            record_fuel_alert(
                site=self.site,
                vehicle_number="PBDN450",
                alert_name="unknown",
                fuel_liters=1,
                epoch_value=1788115579000,
            )