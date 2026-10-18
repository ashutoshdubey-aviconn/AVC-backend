"""Current per-aisle sync/recovery state (``AisleSyncRecoveryStatus``).

Writes are made only when something changes:

* ``mark_sync_healthy`` runs for every stored consumption packet. The last
  written state is cached, so ``healthy -> healthy`` within the same hour
  costs no query; ``last_sync_at`` is refreshed once per observed hour.
* Every other transition writes, and drops the cached state.

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


def _cache_key(site, home_gateway_id, aisle_group):
    return f"sync-status:{_pk(site)}:{home_gateway_id}:{_pk(aisle_group)}"


def _upsert(site, home_gateway_id, aisle_group, defaults):
    defaults = {"updated_at": timezone.now(), **defaults}
    lookup = {
        "site": site,
        "home_gateway_id": str(home_gateway_id),
        "aisle_group": aisle_group,
    }
    if AisleSyncRecoveryStatus.objects.filter(**lookup).update(**defaults):
        return
    try:
        with transaction.atomic():
            AisleSyncRecoveryStatus.objects.create(**lookup, **defaults)
    except IntegrityError:
        # Created concurrently between our UPDATE and INSERT.
        AisleSyncRecoveryStatus.objects.filter(**lookup).update(**defaults)


def _forget_cached_state(site, home_gateway_id, aisle_group):
    key = _cache_key(site, home_gateway_id, aisle_group)
    cache.delete(key)
    transaction.on_commit(lambda: cache.delete(key))


def mark_sync_healthy(site, home_gateway_id, aisle_group, observed_at):
    key = _cache_key(site, home_gateway_id, aisle_group)
    marker = (
        "healthy",
        observed_at.replace(minute=0, second=0, microsecond=0).isoformat(),
    )
    if cache.get(key) == marker:
        return False
    _upsert(
        site,
        home_gateway_id,
        aisle_group,
        {
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "healthy",
            "is_sync_gone": False,
            "recovery_requested": False,
            "recovery_received": False,
            "last_sync_at": observed_at,
            "last_error": None,
        },
    )
    transaction.on_commit(lambda: cache.set(key, marker, STATUS_CACHE_TTL))
    return True


def mark_recovery_requested(
    site, home_gateway_id, aisle_group, missing_from, missing_to
):
    _upsert(
        site,
        home_gateway_id,
        aisle_group,
        {
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "recovery_requested",
            "is_sync_gone": True,
            "recovery_requested": True,
            "recovery_received": False,
            "last_recovery_requested_at": timezone.now(),
            "expected_from": missing_from,
            "expected_to": missing_to,
            "missing_slots": 1,
        },
    )
    _forget_cached_state(site, home_gateway_id, aisle_group)


def mark_recovery_received(site, home_gateway_id, aisle_group):
    _upsert(
        site,
        home_gateway_id,
        aisle_group,
        {
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "recovery_received",
            "is_sync_gone": True,
            "recovery_requested": True,
            "recovery_received": True,
            "last_recovery_received_at": timezone.now(),
        },
    )
    _forget_cached_state(site, home_gateway_id, aisle_group)


def mark_recovered(site, home_gateway_id, aisle_group, recovered_slots):
    _upsert(
        site,
        home_gateway_id,
        aisle_group,
        {
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "recovered",
            "is_sync_gone": False,
            "recovery_requested": False,
            "recovery_received": True,
            "last_recovery_applied_at": timezone.now(),
            "missing_slots": 0,
            "recovered_slots": recovered_slots,
            "last_error": None,
        },
    )
    _forget_cached_state(site, home_gateway_id, aisle_group)
