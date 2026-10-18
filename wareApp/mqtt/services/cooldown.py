"""Per-key cooldowns backed by the Django cache (Redis in production)."""

from django.conf import settings
from django.core.cache import cache


def recovery_request_allowed(site_id, scope, scope_id):
    """Return True only for the first recovery request of a gap per cooldown.

    ``scope`` is ``"aisle"`` (consumption) or ``"source"`` (SupplyTime). The
    first packet of a gap claims the key with an atomic add; packets for the
    same gap inside the cooldown get False and publish nothing.
    """
    timeout = getattr(settings, "MQTT_RECOVERY_REQUEST_COOLDOWN_SECONDS", 600)
    return cache.add(f"mqtt:recovery-req:{site_id}:{scope}:{scope_id}", 1, timeout)
