"""Skip MQTT packets that were already processed (Phase M, step M7).

A packet can reach the processing workers twice: the gateway resends it, two
listeners were subscribed at once, or (with acks_late) a worker died after
the DB commit. Consumption adds each packet's units to the day with
``F() + value``, so a duplicate would double-count.

The guard claims ``sha1(family, site, gateway, payload)`` in the cache with an
atomic add before the handler runs and releases it if the handler raises.
Consumption payloads carry the growing current-hour total, so two different
packets never hash the same.

Only consumption is guarded: it is the one family whose writes are not
idempotent (daily ``F() + units``).

* SupplyTime also increments, but its payload only carries the date and hour,
  so two genuine packets in the same hour with the same runtime are
  byte-identical. It needs a gateway sequence number first.
* load / FIREALARM payloads have no timestamp; identical steady-state readings
  are genuine and refresh "last updated", and their writes are idempotent.
* Recovery writes set values (idempotent); a gateway may legitimately resend
  the same payload in answer to a retried request.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache

GUARDED_FAMILIES = frozenset({"consumption"})


def _ttl():
    return getattr(settings, "MQTT_IDEMPOTENCY_TTL_SECONDS", 6 * 60 * 60)


def message_key(family, site_id, gateway_id, payload):
    digest = hashlib.sha1(
        f"{family}|{site_id}|{gateway_id}|{payload}".encode("utf-8", "replace")
    ).hexdigest()
    return f"mqtt:done:{digest}"


def claim(family, site_id, gateway_id, payload):
    """Return a key to release on failure, or None if this is a duplicate."""
    ttl = _ttl()
    key = message_key(family, site_id, gateway_id, payload)
    if family not in GUARDED_FAMILIES or ttl <= 0:
        return key
    return key if cache.add(key, 1, ttl) else None


def release(key):
    cache.delete(key)
