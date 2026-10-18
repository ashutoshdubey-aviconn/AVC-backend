from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from wareApp.mqtt import sync_status


class SyncStatusTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.site = SimpleNamespace(pk=1)
        self.aisle_group = SimpleNamespace(pk=2, attached_leg_id="967")

    def test_normal_consumption_marks_status_healthy(self):
        with patch("wareApp.mqtt.sync_status._upsert") as upsert, patch(
            "wareApp.mqtt.sync_status.transaction.on_commit"
        ):
            sync_status.mark_sync_healthy(
                self.site, "gateway-01", self.aisle_group, datetime(2026, 10, 17, 9)
            )

        self.assertEqual(upsert.call_args.args[1], "gateway-01")
        self.assertEqual(upsert.call_args.args[3]["sync_status"], "healthy")
        self.assertFalse(upsert.call_args.args[3]["is_sync_gone"])

    def test_recovery_request_marks_sync_as_gone(self):
        with patch("wareApp.mqtt.sync_status._upsert") as upsert, patch(
            "wareApp.mqtt.sync_status.transaction.on_commit"
        ):
            sync_status.mark_recovery_requested(
                self.site,
                "gateway-01",
                self.aisle_group,
                datetime(2026, 10, 17, 8),
                datetime(2026, 10, 17, 9),
            )

        self.assertEqual(upsert.call_args.args[3]["sync_status"], "recovery_requested")
        self.assertTrue(upsert.call_args.args[3]["is_sync_gone"])
