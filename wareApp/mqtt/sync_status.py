"""Low-level writes for the current sync/recovery state (``AisleSyncRecoveryStatus``).

One row exists per (site, gateway, aisle group) for consumption and per
(site, gateway, power source) for SupplyTime / loadRuntime. State transitions
are decided in :mod:`wareApp.mqtt.services.recovery_status`; this module only
writes rows, and does so only when something changes:

* ``mark_sync_healthy`` / ``mark_source_healthy`` run for every stored live
  packet. The last written state is cached, so ``healthy -> healthy`` within
  the same hour costs no query; ``last_sync_at`` is refreshed once per hour.
* Every other transition writes and drops the cached state.

The upsert is a plain ``UPDATE`` followed by ``INSERT`` only for a new row,
instead of ``update_or_create`` (savepoint + ``SELECT ... FOR UPDATE`` +
``UPDATE`` on every call).
"""

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from wareApp.models import AisleSyncRecoveryStatus

STATUS_CACHE_TTL = 2 * 60 * 60


def _pk(value):
    return getattr(value, "pk", None) or getattr(value, "id", None)


def status_lookup(site, home_gateway_id, aisle_group=None, power_source=None):
    lookup = {"site": site, "home_gateway_id": str(home_gateway_id)}
    if aisle_group is not None:
        lookup["aisle_group"] = aisle_group
    else:
        lookup["aisle_group"] = None
        lookup["power_source"] = power_source
    return lookup


def _cache_key(site, home_gateway_id, aisle_group=None, power_source=None):
    scope = f"a{_pk(aisle_group)}" if aisle_group is not None else f"s{power_source}"
    return f"sync-status:{_pk(site)}:{home_gateway_id}:{scope}"


def upsert_status(site, home_gateway_id, defaults, aisle_group=None, power_source=None):
    """Write the status row for the scope; create it if it does not exist yet."""
    defaults = {"updated_at": timezone.now(), **defaults}
    lookup = status_lookup(site, home_gateway_id, aisle_group, power_source)
    if aisle_group is not None:
        defaults.setdefault("leg_id", str(aisle_group.attached_leg_id or ""))
    if not AisleSyncRecoveryStatus.objects.filter(**lookup).update(**defaults):
        try:
            with transaction.atomic():
                AisleSyncRecoveryStatus.objects.create(**lookup, **defaults)
        except IntegrityError:
            # Created concurrently between our UPDATE and INSERT.
            AisleSyncRecoveryStatus.objects.filter(**lookup).update(**defaults)
    key = _cache_key(site, home_gateway_id, aisle_group, power_source)
    cache.delete(key)
    transaction.on_commit(lambda: cache.delete(key))


def _mark_healthy(site, home_gateway_id, observed_at, aisle_group=None, power_source=None):
    key = _cache_key(site, home_gateway_id, aisle_group, power_source)
    marker = (
        "healthy",
        observed_at.replace(minute=0, second=0, microsecond=0).isoformat(),
    )
    if cache.get(key) == marker:
        return False
    upsert_status(
        site,
        home_gateway_id,
        {
            "sync_status": "healthy",
            "is_sync_gone": False,
            "recovery_requested": False,
            "recovery_received": False,
            "last_sync_at": observed_at,
            "last_error": None,
        },
        aisle_group=aisle_group,
        power_source=power_source,
    )
    transaction.on_commit(lambda: cache.set(key, marker, STATUS_CACHE_TTL))
    return True


def mark_sync_healthy(site, home_gateway_id, aisle_group, observed_at):
    """A live consumption packet for the aisle was stored."""
    return _mark_healthy(site, home_gateway_id, observed_at, aisle_group=aisle_group)


def mark_source_healthy(site, home_gateway_id, power_source, observed_at):
    """A live SupplyTime packet for the power source was stored."""
    return _mark_healthy(
        site, home_gateway_id, observed_at, power_source=int(power_source)
    )
