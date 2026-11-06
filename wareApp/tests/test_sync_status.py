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
        with patch("wareApp.mqtt.sync_status.upsert_status") as upsert, patch(
            "wareApp.mqtt.sync_status.transaction.on_commit"
        ):
            sync_status.mark_sync_healthy(
                self.site, "gateway-01", self.aisle_group, datetime(2026, 10, 17, 9)
            )

        self.assertEqual(upsert.call_args.args[1], "gateway-01")
        self.assertEqual(upsert.call_args.args[2]["sync_status"], "healthy")
        self.assertFalse(upsert.call_args.args[2]["is_sync_gone"])
        self.assertIs(upsert.call_args.kwargs["aisle_group"], self.aisle_group)

    def test_source_status_uses_the_power_source_scope(self):
        with patch("wareApp.mqtt.sync_status.upsert_status") as upsert, patch(
            "wareApp.mqtt.sync_status.transaction.on_commit"
        ):
            sync_status.mark_source_healthy(
                self.site, "gateway-01", "2", datetime(2026, 10, 17, 9)
            )

        self.assertEqual(upsert.call_args.kwargs["power_source"], 2)
        self.assertIsNone(upsert.call_args.kwargs["aisle_group"])

    def test_scope_lookup(self):
        self.assertEqual(
            sync_status.status_lookup(self.site, 7, power_source=1),
            {
                "site": self.site,
                "home_gateway_id": "7",
                "aisle_group": None,
                "power_source": 1,
            },
        )
