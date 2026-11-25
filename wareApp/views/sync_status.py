"""Data sync and recovery status of a site (Super_Admin only, read-only).

GET /api/syncStatus/?site_id=114
    Per aisle (consumption) and power source (supply time / load runtime) of the site's gateways
    (decided 2026-11-20, no gap details):
        healthy                 -> sync "synced",  recovery "not_needed",   last_sync_at
        gap filled (recovered)  -> sync "synced",  recovery "recovered",    last_recovered_at
        no data                 -> sync "syncing", recovery "not_received", last_sync_at, attempts
                                   (times the server asked the gateway for this aisle's missing data;
                                   0 = not asked yet, max MQTT_RECOVERY_MAX_ATTEMPTS)
    recovery "received" only shows for the moment between the gateway's answer and its rows being applied.
    From AisleSyncRecoveryStatus, moved by wareApp/mqtt/services/recovery_status.py and the
    recovery_status_sweep command:
        healthy --gap--> recovery_requested --payload--> recovery_received --applied--> recovered --> healthy
        recovery_requested --no answer after MQTT_RECOVERY_MAX_ATTEMPTS--> failed
        healthy --no packet for MQTT_SYNC_LATE_SECONDS (70 min)--> late --MQTT_SYNC_MISSING_SECONDS (130 min)--> missing

GET /api/recoveryHistory/?site_id=114&status=failed&recovery_type=hourly_consumption&limit=50&offset=0
    The recovery requests of the site (RecoveryMonitor), newest first: one row per gap asked from a gateway.
    The raw MQTT payloads are not returned.
"""

from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AisleSyncRecoveryStatus, MeterSource, RecoveryMonitor, Site

__all__ = ["SyncStatusApi", "RecoveryHistoryApi"]

SOURCE_NAMES = dict(MeterSource.POWER_SOURCES)

# Stored state (AisleSyncRecoveryStatus.sync_status) -> (sync, recovery) shown to the frontend.
#   sync: synced = data arriving; syncing = data missing, being asked from the gateway.
#   recovery: was missing data filled?
SYNC_VIEW = {
    "healthy": ("synced", "not_needed"),
    "recovered": ("synced", "recovered"),
    "late": ("syncing", "not_received"),
    "missing": ("syncing", "not_received"),
    "recovery_requested": ("syncing", "not_received"),
    "failed": ("syncing", "not_received"),
    "recovery_received": ("syncing", "received"),
    "unknown": ("unknown", "not_needed"),
}
SYNC_LABELS = {"synced": "Synced", "syncing": "Syncing", "unknown": "Unknown"}
RECOVERY_LABELS = {"not_needed": "Not needed", "recovered": "Recovered", "not_received": "Not received",
                   "received": "Received"}
# Requests that are still open for a gap (their attempt count is the current one).
OPEN_REQUESTS = {"requested", "response_received", "failed", "timeout"}


def _iso(value):
    """Datetime as ISO text, or None.

    Origin: Ashu
    """
    return value.isoformat() if value else None


def _site(request):
    """Site of the request (Super Admin only); None when site_id is missing or unknown.

    Origin: Ashu
    """
    if request.user.UserType != 1:
        raise PermissionDenied("Only Super_Admin users can see the sync and recovery status.")
    try:
        return Site.objects.get(id=int(request.query_params.get("site_id")))
    except (TypeError, ValueError, Site.DoesNotExist):
        return None


def _page(request, default=50, most=500):
    """limit / offset of the request (1-500, default 50); None when they are not numbers.

    Origin: Ashu
    """
    try:
        limit = int(request.query_params.get("limit", default))
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        return None
    return max(1, min(limit, most)), max(0, offset)


def _object(row):
    """What the row is about: an aisle (consumption) or a power source (supply / load).

    Origin: Ashu
    """
    if row.aisle_group_id:
        return "aisle", getattr(row.aisle_group, "aisleGroupName", "") or row.leg_id
    if row.power_source is not None:
        return "power_source", SOURCE_NAMES.get(row.power_source, f"Source {row.power_source}")
    return "unknown", row.leg_id or ""


class SyncStatusApi(APIView):
    """API view for /api/syncStatus/ (GET; Login required). Reads AisleSyncRecoveryStatus. Returns
    counts, data, msg, site_id, site_name, status, total.

    Origin: Ashu
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """GET /api/syncStatus/. No request fields. Response keys: counts, data, msg, site_id,
        site_name, status, total.

        Origin: Ashu
        """
        site = _site(request)
        if site is None:
            return Response({"status": 400, "msg": "Give a valid site_id."}, status=400)
        rows = (
            AisleSyncRecoveryStatus.objects.filter(site=site)
            .select_related("aisle_group", "recovery_monitor")
            .order_by("home_gateway_id", "aisle_group__aisleGroupName", "power_source")
        )
        max_attempts = getattr(settings, "MQTT_RECOVERY_MAX_ATTEMPTS", 3)
        data = []
        counts = {"sync": dict.fromkeys(SYNC_LABELS, 0), "recovery": dict.fromkeys(RECOVERY_LABELS, 0)}
        for row in rows:
            kind, name = _object(row)
            sync, recovery = SYNC_VIEW.get(row.sync_status, ("unknown", "not_needed"))
            counts["sync"][sync] += 1
            counts["recovery"][recovery] += 1
            monitor = row.recovery_monitor
            # Times the server asked the gateway for this aisle's missing data (current gap only).
            attempts = monitor.attempt if sync == "syncing" and monitor and monitor.status in OPEN_REQUESTS else 0
            data.append({
                "id": row.id,
                "home_gateway_id": row.home_gateway_id,
                "object_type": kind,
                "object_name": name,
                "leg_id": row.leg_id,
                "power_source": row.power_source,
                "sync": sync,
                "sync_display": SYNC_LABELS[sync],
                "last_sync_at": _iso(row.last_sync_at),
                "recovery": recovery,
                "recovery_display": RECOVERY_LABELS[recovery],
                "last_recovered_at": _iso(row.last_recovery_applied_at),
                "attempts": attempts,
                "max_attempts": max_attempts,
                # Only for the current gap: an older gap's request time would read as this one's.
                "last_requested_at": _iso(row.last_recovery_requested_at) if attempts else None,
            })
        return Response({
            "status": 200,
            "site_id": site.id,
            "site_name": site.site_name,
            "total": len(data),
            "counts": counts,
            "data": data,
        })


class RecoveryHistoryApi(APIView):
    """API view for /api/recoveryHistory/ (GET; Login required). Reads RecoveryMonitor. Takes
    recovery_type, status. Returns count, limit, msg, offset, results, site_id, status.

    Origin: Ashu
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """GET /api/recoveryHistory/. Request fields: recovery_type, status. Response keys: count,
        limit, msg, offset, results, site_id, status.

        Origin: Ashu
        """
        site = _site(request)
        if site is None:
            return Response({"status": 400, "msg": "Give a valid site_id."}, status=400)
        page = _page(request)
        if page is None:
            return Response({"status": 400, "msg": "limit and offset must be numbers."}, status=400)
        limit, offset = page
        queryset = RecoveryMonitor.objects.filter(site=site).select_related("aisle_group")
        status_value = request.query_params.get("status")
        if status_value:
            queryset = queryset.filter(status=status_value)
        recovery_type = request.query_params.get("recovery_type")
        if recovery_type:
            queryset = queryset.filter(recovery_type=recovery_type)
        total = queryset.count()
        results = []
        for row in queryset.order_by("-requested_at", "-id")[offset:offset + limit]:
            if row.aisle_group_id:
                name = getattr(row.aisle_group, "aisleGroupName", "") or row.leg_id
            elif row.power_source is not None:
                name = SOURCE_NAMES.get(row.power_source, f"Source {row.power_source}")
            else:
                name = row.leg_id or ""
            results.append({
                "id": row.id,
                "recovery_type": row.recovery_type,
                "recovery_type_display": row.get_recovery_type_display(),
                "status": row.status,
                "gateway_id": row.gateway_id,
                "object_name": name,
                "leg_id": row.leg_id,
                "power_source": row.power_source,
                "missing_from": _iso(row.missing_from),
                "missing_to": _iso(row.missing_to),
                "expected_slots": row.expected_slots,
                "recovered_slots": row.recovered_slots,
                "error_slots": row.error_slots,
                "attempt": row.attempt,
                "requested_at": _iso(row.requested_at),
                "response_received_at": _iso(row.response_received_at),
                "applied_at": _iso(row.applied_at),
                "verified_at": _iso(row.verified_at),
                "failed_reason": row.failed_reason,
                "catch_up_at": _iso(row.catch_up_at),
                "is_active": row.is_active,
            })
        return Response({"status": 200, "site_id": site.id, "count": total, "limit": limit, "offset": offset,
                         "results": results})
