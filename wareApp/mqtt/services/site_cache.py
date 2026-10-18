"""Short-lived cache for site configuration read on every MQTT packet.

Site rows and aisle baselines change rarely (when an admin edits them) but are
read for every consumption packet. They are cached for ``CONFIG_CACHE_TTL``
seconds and dropped on ``post_save`` / ``post_delete``. ``QuerySet.update()``
does not send signals, so the TTL bounds how stale a value can get.

The AisleGroup row itself is *not* cached: the consumption handler locks it
with ``select_for_update`` and that lock must stay a database query.
"""

import logging

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from wareApp.models import Site, SiteBaseline

logger = logging.getLogger(__name__)

CONFIG_CACHE_TTL = 300
_MISSING = "__missing__"


def _site_key(site_id):
    return f"cfg:site:{int(site_id)}"


def _baseline_key(site_id, leg_id):
    return f"cfg:baseline:{int(site_id)}:{leg_id}"


def site(site_id):
    """Return the Site (with its customer) or raise ``Site.DoesNotExist``."""
    key = _site_key(site_id)
    cached = cache.get(key)
    if cached == _MISSING:
        raise Site.DoesNotExist(f"Site {site_id} does not exist")
    if cached is not None:
        return cached
    try:
        instance = Site.objects.select_related("customer").get(id=site_id)
    except Site.DoesNotExist:
        # Unknown site IDs arrive from misconfigured gateways on every packet;
        # cache the miss briefly so they do not hit the database each time.
        cache.set(key, _MISSING, 60)
        raise
    cache.set(key, instance, CONFIG_CACHE_TTL)
    return instance


def latest_baseline(site_id, leg_id):
    """Return ``(baseline_value, working_hours)`` of the latest baseline, or None.

    Matches the consumption handler's selection: the row with the latest
    ``baseline_to`` (then highest id) for the site and leg.
    """
    key = _baseline_key(site_id, leg_id)
    cached = cache.get(key)
    if cached == _MISSING:
        return None
    if cached is not None:
        return cached
    baseline = (
        SiteBaseline.objects.filter(
            associated_site_id=int(site_id), leg_id=str(leg_id)
        )
        .order_by("-baseline_to", "-id")
        .values_list("baseline_value", "working_hours")
        .first()
    )
    cache.set(key, _MISSING if baseline is None else tuple(baseline), CONFIG_CACHE_TTL)
    return None if baseline is None else tuple(baseline)


@receiver([post_save, post_delete], sender=Site)
def _drop_site(sender, instance, **kwargs):
    cache.delete(_site_key(instance.pk))


@receiver([post_save, post_delete], sender=SiteBaseline)
def _drop_baseline(sender, instance, **kwargs):
    if instance.associated_site_id_id is not None and instance.leg_id is not None:
        cache.delete(_baseline_key(instance.associated_site_id_id, instance.leg_id))
