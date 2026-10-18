"""Time-based recovery-status transitions (run every 5 minutes).

* Open recovery requests older than the cooldown with no answer -> ``timeout``
  (the next gap packet retries them); at the attempt limit -> ``failed``.
* Aisles whose last stored consumption is older than the late / missing
  thresholds -> ``late`` / ``missing``.

Only the indexed status and monitor tables are read; reading tables are never
scanned. Schedule with deploy/systemd/recovery-status-sweep.timer.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from wareApp.models import AisleSyncRecoveryStatus, RecoveryMonitor


def sweep(now=None):
    now = now or timezone.now()
    cooldown = timedelta(
        seconds=getattr(settings, "MQTT_RECOVERY_REQUEST_COOLDOWN_SECONDS", 600)
    )
    max_attempts = getattr(settings, "MQTT_RECOVERY_MAX_ATTEMPTS", 3)
    late_after = timedelta(seconds=getattr(settings, "MQTT_SYNC_LATE_SECONDS", 4200))
    missing_after = timedelta(
        seconds=getattr(settings, "MQTT_SYNC_MISSING_SECONDS", 7800)
    )

    with transaction.atomic():
        overdue = RecoveryMonitor.objects.filter(
            status="requested", requested_at__lt=now - cooldown
        )
        failed_ids = list(
            overdue.filter(attempt__gte=max_attempts).values_list("id", flat=True)
        )
        failed = RecoveryMonitor.objects.filter(id__in=failed_ids).update(
            status="failed",
            is_active=False,
            failed_reason=f"No response after {max_attempts} attempts",
        )
        AisleSyncRecoveryStatus.objects.filter(recovery_monitor_id__in=failed_ids).update(
            sync_status="failed",
            recovery_requested=False,
            last_error=f"No response after {max_attempts} attempts",
            updated_at=now,
        )
        timed_out = overdue.exclude(id__in=failed_ids).update(status="timeout")

        live = AisleSyncRecoveryStatus.objects.filter(aisle_group__isnull=False)
        missing = live.filter(
            sync_status__in=("healthy", "recovered", "late"),
            last_sync_at__lt=now - missing_after,
        ).update(sync_status="missing", is_sync_gone=True, updated_at=now)
        late = live.filter(
            sync_status__in=("healthy", "recovered"),
            last_sync_at__lt=now - late_after,
        ).update(sync_status="late", updated_at=now)

    return {"failed": failed, "timeout": timed_out, "late": late, "missing": missing}


class Command(BaseCommand):
    help = "Advance time-based recovery and sync status transitions."

    def handle(self, *args, **options):
        result = sweep()
        self.stdout.write(
            "recovery_status_sweep "
            + " ".join(f"{key}={value}" for key, value in result.items())
        )
