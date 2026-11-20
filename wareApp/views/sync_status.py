"""Data sync and recovery status of a site (Super_Admin only, read-only).

GET /api/syncStatus/?site_id=114
    The current state of every aisle (consumption) and power source (supply time / load runtime)
    of the site's gateways: AisleSyncRecoveryStatus, moved by wareApp/mqtt/services/recovery_status.py
    and the recovery_status_sweep command:
        healthy --gap--> recovery_requested --payload--> recovery_received --applied--> recovered --> healthy
        recovery_requested --no answer after MQTT_RECOVERY_MAX_ATTEMPTS--> failed
        healthy --no packet for MQTT_SYNC_LATE_SECONDS (70 min)--> late --MQTT_SYNC_MISSING_SECONDS (130 min)--> missing

GET /api/recoveryHistory/?site_id=114&status=failed&recovery_type=hourly_consumption&limit=50&offset=0
    The recovery requests of the site (RecoveryMonitor), newest first: one row per gap asked from a gateway.
    The raw MQTT payloads are not returned.
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AisleSyncRecoveryStatus, MeterSource, RecoveryMonitor, Site

__all__ = ["SyncStatusApi", "RecoveryHistoryApi"]

SOURCE_NAMES = dict(MeterSource.POWER_SOURCES)
# Order of the states in "counts" (problems first).
STATE_ORDER = ["failed", "missing", "late", "recovery_requested", "recovery_received", "recovered", "healthy", "unknown"]


def _iso(value):
    return value.isoformat() if value else None


def _site(request):
    if request.user.UserType != 1:
        raise PermissionDenied("Only Super_Admin users can see the sync and recovery status.")
    try:
        return Site.objects.get(id=int(request.query_params.get("site_id")))
    except (TypeError, ValueError, Site.DoesNotExist):
        return None


def _page(request, default=50, most=500):
    try:
        limit = int(request.query_params.get("limit", default))
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        return None
    return max(1, min(limit, most)), max(0, offset)


def _object(row):
    """What the row is about: an aisle (consumption) or a power source (supply / load)."""
    if row.aisle_group_id:
        return "aisle", getattr(row.aisle_group, "aisleGroupName", "") or row.leg_id
    if row.power_source is not None:
        return "power_source", SOURCE_NAMES.get(row.power_source, f"Source {row.power_source}")
    return "unknown", row.leg_id or ""


class SyncStatusApi(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        site = _site(request)
        if site is None:
            return Response({"status": 400, "msg": "Give a valid site_id."}, status=400)
        rows = (
            AisleSyncRecoveryStatus.objects.filter(site=site)
            .select_related("aisle_group", "recovery_monitor")
            .order_by("home_gateway_id", "aisle_group__aisleGroupName", "power_source")
        )
        data, counts = [], {state: 0 for state in STATE_ORDER}
        for row in rows:
            kind, name = _object(row)
            monitor = row.recovery_monitor
            counts[row.sync_status] = counts.get(row.sync_status, 0) + 1
            data.append({
                "id": row.id,
                "home_gateway_id": row.home_gateway_id,
                "object_type": kind,
                "object_name": name,
                "aisle_group_id": row.aisle_group_id,
                "leg_id": row.leg_id,
                "power_source": row.power_source,
                "sync_status": row.sync_status,
                "sync_status_display": row.get_sync_status_display(),
                "last_sync_at": _iso(row.last_sync_at),
                "expected_from": _iso(row.expected_from),
                "expected_to": _iso(row.expected_to),
                "missing_slots": row.missing_slots,
                "recovered_slots": row.recovered_slots,
                "has_data_loss": row.has_data_loss,
                "last_error": row.last_error,
                "last_recovery_requested_at": _iso(row.last_recovery_requested_at),
                "last_recovery_received_at": _iso(row.last_recovery_received_at),
                "last_recovery_applied_at": _iso(row.last_recovery_applied_at),
                "updated_at": _iso(row.updated_at),
                "current_recovery": {
                    "id": monitor.id, "recovery_type": monitor.recovery_type, "status": monitor.status,
                    "attempt": monitor.attempt, "requested_at": _iso(monitor.requested_at),
                } if monitor else None,
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
    permission_classes = [IsAuthenticated]

    def get(self, request):
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
