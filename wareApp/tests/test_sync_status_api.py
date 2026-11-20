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
        )
        AisleSyncRecoveryStatus.objects.create(site=self.site, home_gateway_id="avc_sync_000001_1",
                                               power_source=1, sync_status="healthy", last_sync_at=AT)
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))

    def test_sync_status_per_aisle_and_power_source(self):
        body = self.client.get("/api/syncStatus/", {"site_id": self.site.id}).json()
        self.assertEqual((body["total"], body["counts"]["failed"], body["counts"]["healthy"]), (2, 1, 1))
        rows = {row["object_type"]: row for row in body["data"]}
        aisle = rows["aisle"]
        self.assertEqual((aisle["object_name"], aisle["sync_status"], aisle["missing_slots"]), ("Aisle A", "failed", 3))
        self.assertEqual(aisle["current_recovery"]["status"], "failed")
        self.assertEqual(rows["power_source"]["object_name"], "DG_1")
        self.assertIsNone(rows["power_source"]["current_recovery"])

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
