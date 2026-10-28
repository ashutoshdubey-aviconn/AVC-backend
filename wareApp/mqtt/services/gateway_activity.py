"""Last data packet per gateway, as seen by our MQTT listeners.

The listeners call ``seen()`` for every packet. Times are kept in memory and
written once a minute: HomeGatewayStatus.last_data_at (data = consumption,
recovery, load, LoadData) and, for consumption, SiteConsumptionPing (the
same table the former monitoring_dashboard.py cron filled from the broker log).
Server-originated topics (in/sync/...) are not gateway data and never reach
these listeners' handlers. Gateway health alarms read these times
(wareApp/mqtt/services/gateway_health.py).
"""

import logging
import threading
import time
from datetime import datetime

from wareApp.models import HomeGatewayId, HomeGatewayStatus, Site, SiteConsumptionPing

logger = logging.getLogger(__name__)

DATA_TYPES = frozenset({"consumption", "recovery", "load", "LoadData"})
FLUSH_SECONDS = 60

_lock = threading.Lock()
_pending = {}  # home gateway id -> {"site_id", "data_at", "consumption_at"}
_last_flush = time.monotonic()


def seen(site_id, gateway_id, message_type, now=None):
    """Note one packet; writes the collected times at most once a minute."""
    if message_type not in DATA_TYPES or not gateway_id:
        return
    now = now or datetime.now()
    with _lock:
        entry = _pending.setdefault(gateway_id, {"site_id": site_id})
        entry["data_at"] = now
        if message_type == "consumption":
            entry["consumption_at"] = now
        due = time.monotonic() - _last_flush >= FLUSH_SECONDS
    if due:
        flush()


def flush():
    """Write the collected times; returns the number of gateways written."""
    global _last_flush
    with _lock:
        pending = dict(_pending)
        _pending.clear()
        _last_flush = time.monotonic()
    if not pending:
        return 0
    try:
        known = dict(
            HomeGatewayId.objects.filter(hgw_id__in=list(pending)).values_list("hgw_id", "id")
        )
        statuses = {
            status.home_gateway_id: status
            for status in HomeGatewayStatus.objects.filter(home_gateway_id__in=known.values())
        }
        to_update, to_create = [], []
        for gateway_id, entry in pending.items():
            hgw_pk = known.get(gateway_id)
            if hgw_pk is None:
                continue
            status = statuses.get(hgw_pk)
            if status is None:
                to_create.append(
                    HomeGatewayStatus(home_gateway_id=hgw_pk, status=True, last_data_at=entry["data_at"])
                )
            else:
                status.last_data_at = entry["data_at"]
                status.status = True
                to_update.append(status)
        HomeGatewayStatus.objects.bulk_update(to_update, ["last_data_at", "status"])
        HomeGatewayStatus.objects.bulk_create(to_create)
        sites = set(
            Site.objects.filter(
                id__in={entry.get("site_id") for entry in pending.values() if entry.get("site_id")}
            ).values_list("id", flat=True)
        )
        for gateway_id, entry in pending.items():
            if entry.get("consumption_at") and entry.get("site_id") in sites:
                updated = SiteConsumptionPing.objects.filter(
                    site_id=entry["site_id"], home_gateway_id=gateway_id
                ).update(consumption_ping_time=entry["consumption_at"])
                if not updated:
                    SiteConsumptionPing.objects.create(
                        site_id=entry["site_id"],
                        home_gateway_id=gateway_id,
                        consumption_ping_time=entry["consumption_at"],
                    )
        return len(to_update) + len(to_create)
    except Exception:
        # Monitoring only: never break packet intake. Keep the times for the next try.
        logger.exception("Gateway activity flush failed (%s gateways)", len(pending))
        with _lock:
            for gateway_id, entry in pending.items():
                _pending.setdefault(gateway_id, entry)
        return 0
