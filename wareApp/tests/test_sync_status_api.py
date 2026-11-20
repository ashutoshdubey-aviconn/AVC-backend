"""syncStatus/ and recoveryHistory/: read-only sync / recovery state of a site (Super_Admin only)."""

from datetime import datetime

from django.test import TestCase
from rest_framework.test import APIClient

from wareApp.models import AisleGroup, AisleSyncRecoveryStatus, RecoveryMonitor, Site, User

AT = datetime(2026, 11, 20, 9, 0)


class SyncStatusApiTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="Sync site", site_type=2, is_live=True)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="Aisle A", is_active=True)
        self.aisle.refresh_from_db()
        leg = self.aisle.attached_leg_id
        self.monitor = RecoveryMonitor.objects.create(
            site=self.site, gateway_id="avc_sync_000001_1", aisle_group=self.aisle, leg_id=leg,
            recovery_type="hourly_consumption", status="failed", missing_from=AT, missing_to=AT,
            expected_slots=3, error_slots=3, attempt=3, failed_reason="no answer", requested_at=AT,
            mqtt_request_payload='{"secret": "not returned"}',
        )
        RecoveryMonitor.objects.create(site=self.site, gateway_id="avc_sync_000001_1", power_source=1,
                                       recovery_type="load_runtime", status="verified", missing_from=AT,
                                       requested_at=datetime(2026, 11, 19, 9, 0))
        AisleSyncRecoveryStatus.objects.create(
            site=self.site, home_gateway_id="avc_sync_000001_1", aisle_group=self.aisle, leg_id=leg,
            sync_status="failed", missing_slots=3, last_sync_at=AT, recovery_monitor=self.monitor,
            last_recovery_requested_at=datetime(2026, 11, 20, 9, 30),
        )
        AisleSyncRecoveryStatus.objects.create(site=self.site, home_gateway_id="avc_sync_000001_1",
                                               power_source=1, sync_status="healthy", last_sync_at=AT,
                                               last_recovery_applied_at=datetime(2026, 11, 19, 10, 0))
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))

    def test_synced_and_syncing_rows(self):
        body = self.client.get("/api/syncStatus/", {"site_id": self.site.id}).json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["counts"]["sync"], {"synced": 1, "syncing": 1, "unknown": 0})
        self.assertEqual(body["counts"]["recovery"], {"not_needed": 1, "recovered": 0, "not_received": 1, "received": 0})
        rows = {row["object_type"]: row for row in body["data"]}
        aisle, source = rows["aisle"], rows["power_source"]
        # No data: Syncing, recovery Not received, how many times it was asked.
        self.assertEqual((aisle["object_name"], aisle["sync_display"], aisle["recovery_display"]),
                         ("Aisle A", "Syncing", "Not received"))
        self.assertEqual((aisle["attempts"], aisle["max_attempts"]), (3, 3))
        self.assertTrue(aisle["last_requested_at"].startswith("2026-11-20T09:30"))
        self.assertIsNone(aisle["last_recovered_at"])
        # Healthy: Synced, recovery Not needed, last sync time; no attempts.
        self.assertEqual((source["object_name"], source["sync_display"], source["recovery_display"]),
                         ("DG_1", "Synced", "Not needed"))
        self.assertTrue(source["last_sync_at"].startswith("2026-11-20T09:00"))
        self.assertEqual((source["attempts"], source["last_requested_at"]), (0, None))
        self.assertTrue(source["last_recovered_at"].startswith("2026-11-19T10:00"))
        for gone in ("expected_from", "expected_to", "missing_slots", "recovered_slots", "current_recovery", "sync_status"):
            self.assertNotIn(gone, aisle)

    def test_old_request_is_not_shown_as_an_attempt_for_a_new_gap(self):
        old = RecoveryMonitor.objects.create(site=self.site, gateway_id="avc_sync_000001_1", power_source=2,
                                             recovery_type="load_runtime", status="verified", attempt=2,
                                             missing_from=AT, requested_at=datetime(2026, 11, 6, 11, 0))
        AisleSyncRecoveryStatus.objects.create(site=self.site, home_gateway_id="avc_sync_000001_1", power_source=2,
                                               sync_status="missing", recovery_monitor=old,
                                               last_recovery_requested_at=datetime(2026, 11, 6, 11, 0))
        body = self.client.get("/api/syncStatus/", {"site_id": self.site.id}).json()
        row = next(r for r in body["data"] if r["power_source"] == 2)
        self.assertEqual((row["sync"], row["attempts"], row["last_requested_at"]), ("syncing", 0, None))

    def test_states_map_to_sync_and_recovery(self):
        from wareApp.views.sync_status import SYNC_VIEW
        self.assertEqual(SYNC_VIEW["healthy"], ("synced", "not_needed"))
        self.assertEqual(SYNC_VIEW["recovered"], ("synced", "recovered"))
        for state in ("late", "missing", "recovery_requested", "failed"):
            self.assertEqual(SYNC_VIEW[state], ("syncing", "not_received"))

    def test_recovery_history_newest_first_filtered_without_payloads(self):
        body = self.client.get("/api/recoveryHistory/", {"site_id": self.site.id}).json()
        self.assertEqual(body["count"], 2)
        self.assertEqual([r["recovery_type"] for r in body["results"]], ["hourly_consumption", "load_runtime"])
        self.assertNotIn("mqtt_request_payload", body["results"][0])
        self.assertEqual(body["results"][1]["object_name"], "DG_1")
        failed = self.client.get("/api/recoveryHistory/", {"site_id": self.site.id, "status": "failed", "limit": 1}).json()
        self.assertEqual((failed["count"], failed["limit"], failed["results"][0]["failed_reason"]), (1, 1, "no answer"))

    def test_errors_and_access(self):
        self.assertEqual(self.client.get("/api/syncStatus/", {"site_id": 999999}).status_code, 400)
        self.assertEqual(self.client.get("/api/recoveryHistory/", {"site_id": self.site.id, "limit": "x"}).status_code, 400)
        other = APIClient()
        other.force_authenticate(User.objects.create(username="customer", UserType=4))
        self.assertEqual(other.get("/api/syncStatus/", {"site_id": self.site.id}).status_code, 403)
        self.assertEqual(other.get("/api/recoveryHistory/", {"site_id": self.site.id}).status_code, 403)
        self.assertEqual(APIClient().get("/api/syncStatus/", {"site_id": self.site.id}).status_code, 401)
