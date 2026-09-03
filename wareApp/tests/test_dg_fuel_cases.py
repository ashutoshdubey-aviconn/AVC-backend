from django.test import TestCase
from unittest.mock import patch
from django.utils import timezone
from datetime import timedelta

from wareApp.models import (
    Site,
    AisleGroup,
    DailySiteReading,
    DgUnitConsumption,
    DGFuelAlertsData,
    NewAlarmsNotifications,
)
from wareApp.dg_fuel.sessions import (
    attempt_fetch_for_unit,
    reconcile_daily_unit_consumption,
)


class DgFuelEdgeCasesTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            site_name="Edge Site",
            partner_dg_fuel_id="99999",
            partner_dg_provider="roadcast",
            dg_fuel_tank_capacity=50,
        )
        self.aisle = AisleGroup.objects.create(
            site=self.site, aisleGroupName="A1", power_source=1
        )

    def make_daily_reading(self, aisle=None, unit_consumption=79.69):
        aisle = aisle or self.aisle
        return DailySiteReading.objects.create(
            associated_Site=self.site,
            aisle_group=aisle,
            leg_id=str(aisle.id),
            unit_consumption=unit_consumption,
            daily_baseline_value=0,
            reading_for=timezone.now().date(),
            is_visible=True,
        )

    def make_unit(self, unit_consumption=None, start_offset_min=60, end_offset_min=0):
        now = timezone.now()
        start = now - timedelta(minutes=start_offset_min)
        end = now - timedelta(minutes=end_offset_min)
        return DgUnitConsumption.objects.create(
            site=self.site,
            aisle_group=self.aisle,
            unit_consumption=unit_consumption,
            dg_fuel_consumption=None,
            dg_start_date=start,
            dg_end_date=end,
            is_dg_on=False,
            fetch_fuel_data=True,
        )

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_zero_fuel_success(self, mock_fetch):
        self.make_daily_reading(unit_consumption=0)
        reconcile_daily_unit_consumption(self.site)
        mock_fetch.return_value = 0
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertTrue(ok)
        self.assertEqual(unit.dg_fuel_consumption, 0)
        self.assertFalse(unit.fetch_fuel_data)

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_invalid_fuel_value_stays_unset_and_retries(self, mock_fetch):
        self.make_daily_reading(unit_consumption=79.69)
        reconcile_daily_unit_consumption(self.site)
        mock_fetch.return_value = "abc"
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertFalse(ok)
        self.assertTrue(unit.fetch_fuel_data)
        self.assertEqual(unit.unit_consumption, 79.69)
        self.assertIsNone(unit.dg_fuel_consumption)

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_missing_daily_reading_defers_fetch(self, mock_fetch):
        mock_fetch.return_value = 12.5
        unit = self.make_unit()
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertFalse(ok)
        self.assertIsNone(unit.unit_consumption)
        self.assertTrue(unit.fetch_fuel_data)
        mock_fetch.assert_not_called()

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_no_dg_run_alarm_created_when_unit_consumption_zero(self, mock_fetch):
        self.make_daily_reading(unit_consumption=0)
        reconcile_daily_unit_consumption(self.site)
        mock_fetch.return_value = 12.5
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        self.assertTrue(ok)
        self.assertTrue(
            NewAlarmsNotifications.objects.filter(
                site_id=self.site, alarm_type=9
            ).exists()
        )

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_no_alert_when_tank_none(self, mock_fetch):
        self.make_daily_reading(unit_consumption=79.69)
        reconcile_daily_unit_consumption(self.site)
        mock_fetch.return_value = 1000
        self.site.dg_fuel_tank_capacity = None
        self.site.save()
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        self.assertTrue(ok)
        self.assertFalse(
            DGFuelAlertsData.objects.filter(
                site=self.site, alert_name="suspicious_fuel"
            ).exists()
        )

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_on_off_event_triggers_fetch(self, mock_fetch):
        self.make_daily_reading(unit_consumption=79.69)
        reconcile_daily_unit_consumption(self.site)
        mock_fetch.return_value = 5.5
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertTrue(ok)
        self.assertFalse(unit.fetch_fuel_data)
        self.assertEqual(unit.unit_consumption, 79.69)
        self.assertEqual(unit.dg_fuel_consumption, 5.5)

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_dg_unit_reconciliation_is_idempotent(self, mock_fetch):
        self.make_daily_reading(unit_consumption=79.69)
        first = reconcile_daily_unit_consumption(self.site)
        second = reconcile_daily_unit_consumption(self.site)
        mock_fetch.return_value = 5.5
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(
            DgUnitConsumption.objects.filter(
                site=self.site,
                aisle_group=self.aisle,
                created__date=timezone.now().date(),
            ).count(),
            1,
        )
        self.assertTrue(ok)
        self.assertEqual(unit.unit_consumption, 79.69)
        self.assertEqual(unit.dg_fuel_consumption, 5.5)

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_daily_reading_is_aisle_scoped(self, mock_fetch):
        other_aisle = AisleGroup.objects.create(
            site=self.site, aisleGroupName="A2", power_source=1
        )
        self.make_daily_reading(aisle=self.aisle, unit_consumption=79.69)
        reconcile_daily_unit_consumption(self.site)
        mock_fetch.return_value = 4.2
        units = DgUnitConsumption.objects.filter(site=self.site)
        self.assertEqual(units.count(), 1)
        unit_one = units.get(aisle_group=self.aisle)
        ok_one = attempt_fetch_for_unit(unit_one)
        unit_one.refresh_from_db()

        self.assertTrue(ok_one)
        self.assertEqual(unit_one.unit_consumption, 79.69)
        self.assertEqual(unit_one.dg_fuel_consumption, 4.2)

        self.assertFalse(DgUnitConsumption.objects.filter(site=self.site, aisle_group=other_aisle).exists())

    def test_dgfuel_model_and_alert_creation(self):
        # create a DgFuelConsumptionData row and verify fields
        from wareApp.models import DgFuelConsumptionData, DGFuelAlertsData

        d = DgFuelConsumptionData.objects.create(
            site=self.site,
            vehicle_number="V-1",
            fuel_consumption=12.34,
            fuel_data_source="loconav",
            epoch_time="1234567890000",
        )
        self.assertEqual(str(d), "V-1")

        # create an alert and verify string/fields
        a = DGFuelAlertsData.objects.create(
            site=self.site,
            alert_name="theft",
            vehicle_number="V-1",
            fuel_consumption=4.5,
            epoch_time="1234567",
        )
        self.assertEqual(str(a), "theft")
