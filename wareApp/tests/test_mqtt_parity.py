"""Parity rules carried over from the legacy root tasks.py (Phase M, step M1)."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from wareApp.mqtt import (
    consumption,
    daily_consumption_recovery,
    hourly_consumption_recovery,
    load_runtime_recovery,
)
from wareApp.mqtt.payloads import split_paired_lists


class WarehouseSavingCapTests(SimpleTestCase):
    def values(self):
        return {
            "new_unit_consumption": 12000.0,
            "current_hour_consumption": 15000.0,
            "previous_hour_consumption": 9.5,
        }

    def test_energy_saving_site_values_above_limit_become_zero(self):
        values = consumption._cap_warehouse_saving_values(
            SimpleNamespace(id=1, site_type=2), self.values()
        )

        self.assertEqual(values["new_unit_consumption"], 0.0)
        self.assertEqual(values["current_hour_consumption"], 0.0)
        self.assertEqual(values["previous_hour_consumption"], 9.5)

    def test_other_site_types_are_not_capped(self):
        values = consumption._cap_warehouse_saving_values(
            SimpleNamespace(id=1, site_type=1), self.values()
        )

        self.assertEqual(values["new_unit_consumption"], 12000.0)


class RecoveryListPairingTests(SimpleTestCase):
    def test_trailing_commas_are_ignored(self):
        self.assertEqual(
            split_paired_lists("a,b,", "1,2,", "test"), (["a", "b"], ["1", "2"])
        )

    def test_mismatched_lists_are_rejected(self):
        with self.assertRaises(ValueError):
            split_paired_lists("a,b,c", "1,2", "test")

    def test_hourly_parser_rejects_mismatched_lists(self):
        message = (
            "Aisle_group_id : 967; Recovery_Hours : 2026-10-16 01:00:00.000,"
            "2026-10-16 02:00:00.000,; Unit_consumptions : 0.1,; "
            "GW_total_cumulative : 0"
        )
        with self.assertRaises(ValueError):
            hourly_consumption_recovery._parse_hourly_recovery_message(message)

    def test_daily_parser_rejects_mismatched_lists(self):
        message = (
            "Aisle_group_id : 967; Recovery_Dates : 2026-10-16,; "
            "Unit_consumptions : 1.0,2.0,; GW_Total_cumulative : 0"
        )
        with self.assertRaises(ValueError):
            daily_consumption_recovery._parse_daily_recovery_message(message)

    def test_runtime_parser_rejects_mismatched_lists(self):
        message = (
            "Power_source : 1; Recovery_hours : 2026-10-16 01:00:00.000,; "
            "Recovery_load_runtime : 10,20,"
        )
        with self.assertRaises(ValueError):
            load_runtime_recovery._parse_load_runtime_recovery_message(message)
