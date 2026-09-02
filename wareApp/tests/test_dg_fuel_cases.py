from django.test import TestCase
from unittest.mock import patch
from django.utils import timezone
from datetime import timedelta

from wareApp.models import (
    Site,
    AisleGroup,
    DgUnitConsumption,
    DGFuelAlertsData,
    NewAlarmsNotifications,
)
from wareApp.dg_fuel.sessions import (
    attempt_fetch_for_unit,
    on_event,
    update_event,
    off_event,
)


class DgFuelEdgeCasesTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            site_name="Edge Site", partner_dg_fuel_id="99999", dg_fuel_tank_capacity=50
        )
        self.aisle = AisleGroup.objects.create(
            site=self.site, aisleGroupName="A1", power_source=1
        )

    def make_unit(self, unit_consumption=10, start_offset_min=60, end_offset_min=0):
        now = timezone.now()
        start = now - timedelta(minutes=start_offset_min)
        end = now - timedelta(minutes=end_offset_min)
        return DgUnitConsumption.objects.create(
            site=self.site,
            aisle_group=self.aisle,
            unit_consumption=unit_consumption,
            dg_start_date=start,
            dg_end_date=end,
            is_dg_on=False,
            fetch_fuel_data=True,
        )

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_zero_fuel_success(self, mock_fetch):
        mock_fetch.return_value = 0
        unit = self.make_unit()
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertTrue(ok)
        self.assertEqual(unit.dg_fuel_consumption, 0)
        self.assertFalse(unit.fetch_fuel_data)

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_non_numeric_parsed_to_zero(self, mock_fetch):
        mock_fetch.return_value = "abc"
        unit = self.make_unit()
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertTrue(ok)
        self.assertEqual(unit.dg_fuel_consumption, 0)
        self.assertFalse(unit.fetch_fuel_data)

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_no_dg_run_alarm_created_when_unit_consumption_zero(self, mock_fetch):
        mock_fetch.return_value = 12.5
        unit = self.make_unit(unit_consumption=0)
        ok = attempt_fetch_for_unit(unit)
        self.assertTrue(ok)
        self.assertTrue(
            NewAlarmsNotifications.objects.filter(
                site_id=self.site, alarm_type=9
            ).exists()
        )

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_no_alert_when_tank_none(self, mock_fetch):
        mock_fetch.return_value = 1000
        self.site.dg_fuel_tank_capacity = None
        self.site.save()
        unit = self.make_unit()
        ok = attempt_fetch_for_unit(unit)
        self.assertTrue(ok)
        self.assertFalse(
            DGFuelAlertsData.objects.filter(
                site=self.site, alert_name="suspicious_fuel"
            ).exists()
        )

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_on_off_event_triggers_fetch(self, mock_fetch):
        mock_fetch.return_value = 5.5
        entry_time = timezone.now()
        on_event(self.site, self.aisle, entry_time)
        active = off_event(self.site, self.aisle, entry_time)
        self.assertIsNotNone(active)
        active.refresh_from_db()
        self.assertFalse(active.fetch_fuel_data)
        self.assertEqual(active.dg_fuel_consumption, 5.5)

    def test_dg_unit_update_coalescing(self):
        # Ensure multiple updates accumulate into the same active run
        entry_time = timezone.now()
        on_event(self.site, self.aisle, entry_time)
        # two updates
        update_event(self.site, self.aisle, 2.5, entry_time + timedelta(minutes=1))
        update_event(self.site, self.aisle, 3.5, entry_time + timedelta(minutes=2))
        # close run
        active = off_event(self.site, self.aisle, entry_time + timedelta(minutes=3))
        self.assertIsNotNone(active)
        active.refresh_from_db()
        self.assertEqual(active.unit_consumption, 6.0)

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
