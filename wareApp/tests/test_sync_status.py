from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from wareApp.mqtt import sync_status


class SyncStatusTests(SimpleTestCase):
    def setUp(self):
        self.site = SimpleNamespace()
        self.aisle_group = SimpleNamespace(attached_leg_id="967")

    def test_normal_consumption_marks_status_healthy(self):
        with patch(
            "wareApp.mqtt.sync_status.AisleSyncRecoveryStatus.objects.update_or_create"
        ) as update:
            sync_status.mark_sync_healthy(
                self.site, "gateway-01", self.aisle_group, datetime(2026, 10, 17, 9)
            )

        self.assertEqual(update.call_args.kwargs["home_gateway_id"], "gateway-01")
        self.assertEqual(update.call_args.kwargs["defaults"]["sync_status"], "healthy")
        self.assertFalse(update.call_args.kwargs["defaults"]["is_sync_gone"])

    def test_recovery_request_marks_sync_as_gone(self):
        with patch(
            "wareApp.mqtt.sync_status.AisleSyncRecoveryStatus.objects.update_or_create"
        ) as update:
            sync_status.mark_recovery_requested(
                self.site,
                "gateway-01",
                self.aisle_group,
                datetime(2026, 10, 17, 8),
                datetime(2026, 10, 17, 9),
            )

        self.assertEqual(
            update.call_args.kwargs["defaults"]["sync_status"], "recovery_requested"
        )
        self.assertTrue(update.call_args.kwargs["defaults"]["is_sync_gone"])
