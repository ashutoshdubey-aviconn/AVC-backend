"""LoadData failures become dead letters and can be replayed.

Before: handle_load_data_message logged every error and dropped the packet,
including transient database errors (no retry) - 157 readings were lost on
the test server during a 90-second incident.
"""

from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import TestCase

from wareApp.load_data import handler, rollups
from wareApp.models import AisleGroup, MqttDeadLetter, RawLoadData, Site


def load_message(leg, second=56, value=12.5):
    return (
        f"b'load_value:{value},leg_id:{leg},meter_number:99,"
        f"date:2026-09-30 12:34:{second:02d}.000000,epoch:16960772{second:02d}'"
    )


class LoadDataDeadLetterTests(TestCase):
    def setUp(self):
        cache.clear()
        rollups._last_rollup_minute_by_site.clear()
        rollups._last_daily_rollup_hour_by_site.clear()
        rollups._rollup_locks_by_site.clear()
        self.site = Site.objects.create(site_name="Load site", site_type=1)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="L1")
        self.aisle.refresh_from_db()
        self.leg = self.aisle.attached_leg_id

    def handle(self, message):
        return handler.handle_load_data_message(
            None, self.site, self.site.id, "gw-1", message, ["LoadData"]
        )

    def test_valid_packet_is_stored_with_outcome(self):
        outcome = self.handle(load_message(self.leg))
        self.assertTrue(outcome.startswith("stored: LoadData leg"))
        self.assertEqual(RawLoadData.objects.count(), 1)

    def test_configuration_error_is_stored_once_per_gateway(self):
        for second in (10, 11, 12):
            outcome = self.handle(load_message("999999", second))  # unknown leg
            self.assertTrue(outcome.startswith("failed: DoesNotExist"))
        self.assertEqual(MqttDeadLetter.objects.filter(message_type="LoadData").count(), 1)

    def test_unexpected_error_keeps_every_packet(self):
        with mock.patch.object(handler, "save_raw_load_reading", side_effect=ValueError) as save:
            save.side_effect = RuntimeError("router prevents this relation")
            for second in (10, 11, 12):
                self.handle(load_message(self.leg, second))
        rows = MqttDeadLetter.objects.filter(message_type="LoadData")
        self.assertEqual(rows.count(), 3)
        self.assertIn("RuntimeError", rows.first().error)

    def test_transient_database_error_is_raised_for_retry(self):
        with mock.patch.object(handler, "save_raw_load_reading", side_effect=OperationalError("gone")):
            with self.assertRaises(OperationalError):
                self.handle(load_message(self.leg))
        self.assertFalse(MqttDeadLetter.objects.exists())


class ReplayDeadLettersCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        rollups._last_rollup_minute_by_site.clear()
        rollups._last_daily_rollup_hour_by_site.clear()
        rollups._rollup_locks_by_site.clear()
        self.site = Site.objects.create(site_name="Replay site", site_type=1)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="R1")
        self.aisle.refresh_from_db()

    def dead_letter(self, payload, message_type="LoadData"):
        return MqttDeadLetter.objects.create(
            message_type=message_type, site_id=self.site.id, gateway_id="gw-1",
            payload=payload, error="RuntimeError: router prevents this relation",
        )

    def run_command(self, *args):
        out = StringIO()
        call_command("replay_dead_letters", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        self.dead_letter(load_message(self.aisle.attached_leg_id))
        output = self.run_command("--type", "LoadData")
        self.assertIn("1 unresolved dead letters: LoadData=1", output)
        self.assertIn("dry run", output)
        self.assertEqual(RawLoadData.objects.count(), 0)

    def test_apply_stores_and_resolves(self):
        ok = self.dead_letter(load_message(self.aisle.attached_leg_id, 20))
        bad = self.dead_letter(load_message("999999", 21))
        output = self.run_command("--type", "LoadData", "--apply")
        self.assertIn("resolved 1, still failing 1", output)
        self.assertEqual(RawLoadData.objects.count(), 1)
        ok.refresh_from_db()
        bad.refresh_from_db()
        self.assertTrue(ok.is_resolved)
        self.assertFalse(bad.is_resolved)
        self.assertIn("replayed 0", self.run_command("--id", str(ok.id), "--apply"))

    def test_order_sensitive_types_need_explicit_flag(self):
        self.dead_letter("Consumption:1", message_type="consumption")
        with self.assertRaises(CommandError):
            self.run_command("--apply")
