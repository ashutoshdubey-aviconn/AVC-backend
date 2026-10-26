"""Active alarms for the dashboards: one row per issue.

All alarms live in ``AlarmNotifications`` (one table since migration 0099):
consumption alarms per aisle, meter / gateway alarms per object, power and DG
alarms per power source. Repeats are counted on one row per day; this module
groups an issue's days into one row (first seen, last seen, total occurrences)
with the site, customer, aisle group, leg, power source, home gateway and the
latest details. A fixed number of queries, independent of the data volume.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Max, Min, Q, Sum

from wareApp.models import (
    AisleSyncRecoveryStatus,
    AlarmNotifications,
    HomeGatewayId,
    Site,
)

# Priority labels as the dashboard shows them (0 High, 1 Medium, 2 Low).
PRIORITY_LABELS = {0: "High", 1: "Medium", 2: "Low"}

ALARM_TYPES = dict(AlarmNotifications._meta.get_field("Alarm_type").flatchoices)
GATEWAY_OVERHEAT = AlarmNotifications.GATEWAY_OVERHEAT


def _fmt(value):
    return None if value is None else f"{float(value):g}"


def _power_issue(row):
    """Readable details of a voltage / PF / DG alarm row."""
    alarm_type = row.Alarm_type
    phases = "/".join(_fmt(v) or "-" for v in (row.r_phase, row.y_phase, row.b_phase))
    if alarm_type in (0, 1):
        return f"R/Y/B voltage {phases} V"
    if alarm_type == 2:
        return f"R/Y/B power factor {phases}"
    if row.fuel_level is not None:
        return f"Fuel {_fmt(row.fuel_level)} L"
    if row.run_hours is not None:
        return f"Run hours {_fmt(row.run_hours)}"
    return ALARM_TYPES.get(alarm_type, "")


def _cutoff():
    """Oldest last-seen time shown (ALARM_FEED_MAX_AGE_DAYS; 0 = no limit)."""
    days = getattr(settings, "ALARM_FEED_MAX_AGE_DAYS", 30)
    return datetime.now() - timedelta(days=days) if days else None


def active_alarms(site_ids):
    """List of issue rows (dicts) for the given sites, newest activity first.

    Issues whose latest occurrence is older than ALARM_FEED_MAX_AGE_DAYS are
    left out; the filter applies to the whole issue, so "since" still shows
    when it really started.
    """
    site_ids = list(site_ids)
    cutoff = _cutoff()
    if not site_ids:
        return []
    sites = {
        site.id: site
        for site in Site.objects.filter(id__in=site_ids).select_related("customer")
    }
    site_gateways = defaultdict(list)
    for site_id, hgw_id in HomeGatewayId.objects.filter(
        connected_to__in=site_ids
    ).values_list("connected_to", "hgw_id"):
        site_gateways[site_id].append(hgw_id)

    rows = []
    groups = list(
        AlarmNotifications.objects.filter(site_id__in=site_ids, is_active=True)
        .values("site_id", "aisle_group_id", "object_id", "power_source", "Alarm_type")
        .annotate(
            first_seen=Min("created_time"),
            last_created=Max("created_time"),
            last_seen=Max("last_seen"),
            occurrences=Sum("occurrences"),
            # 0 High, 1 Medium, 2 Low: the most severe of the issue's rows.
            priority=Min("Alarm_priority"),
            latest_id=Max("id"),
        )
        .filter(
            Q(last_created__gte=cutoff) | Q(last_seen__gte=cutoff) if cutoff else Q()
        )
    )
    latest = {
        alarm.id: alarm
        for alarm in AlarmNotifications.objects.filter(
            id__in=[g["latest_id"] for g in groups]
        ).select_related("aisle_group")
    }
    aisle_gateways = dict(
        AisleSyncRecoveryStatus.objects.filter(
            site_id__in=site_ids,
            aisle_group_id__in={
                g["aisle_group_id"] for g in groups if g["aisle_group_id"]
            },
        ).values_list("aisle_group_id", "home_gateway_id")
    )
    for group in groups:
        alarm = latest[group["latest_id"]]
        site = sites[group["site_id"]]
        alarm_type = group["Alarm_type"]
        all_gateways = ", ".join(site_gateways.get(site.id, [])) or None
        last_seen = max(
            d for d in (group["last_created"], group["last_seen"]) if d is not None
        )
        common = dict(
            alarm_type=alarm_type,
            alarm=ALARM_TYPES.get(alarm_type, str(alarm_type)),
            priority=group["priority"],
            first_seen=group["first_seen"],
            last_seen=last_seen,
            occurrences=group["occurrences"] or 1,
        )
        if alarm.source == "gateway":
            # object_id is the gateway number (…_<n> in the home gateway id).
            number = group["object_id"]
            home_gateway = next(
                (
                    g
                    for g in site_gateways.get(site.id, [])
                    if number is not None and g.endswith(f"_{number}")
                ),
                all_gateways,
            )
            rows.append(_row(
                site, source="gateway", aisle_group_id=None, aisle_group_name=None,
                leg_id=None, power_source=None, home_gateway_id=home_gateway,
                issue=alarm.to_do or "Gateway CPU temperature high", **common,
            ))
        elif alarm.source == "power":
            rows.append(_row(
                site, source="power", aisle_group_id=None, aisle_group_name=None,
                leg_id=None, power_source=group["power_source"],
                home_gateway_id=all_gateways, issue=_power_issue(alarm), **common,
            ))
        else:
            aisle = alarm.aisle_group
            rows.append(_row(
                site,
                source="consumption",
                aisle_group_id=aisle.id if aisle else None,
                aisle_group_name=aisle.aisleGroupName if aisle else None,
                leg_id=(aisle.attached_leg_id if aisle else None) or group["object_id"],
                power_source=None,
                home_gateway_id=aisle_gateways.get(group["aisle_group_id"]) or all_gateways,
                issue=alarm.to_do or ALARM_TYPES.get(alarm_type, ""),
                **common,
            ))

    # Some old power alarm rows have no time; they sort last.
    rows.sort(
        key=lambda r: r["last_seen"] or r["created_time"] or datetime.min, reverse=True
    )
    return rows


def _row(site, *, first_seen, priority, alarm, **fields):
    customer = site.customer
    return {
        # Keys the existing dashboard table already reads:
        "alarm": alarm,
        "Alarm_priority": priority,
        "site_id__site_name": site.site_name,
        "created_time": first_seen,
        # Added context:
        "priority": PRIORITY_LABELS.get(priority, str(priority)),
        "site_id": site.id,
        "customer_id": customer.id if customer else None,
        "customer_name": customer.username if customer else None,
        **fields,
    }
