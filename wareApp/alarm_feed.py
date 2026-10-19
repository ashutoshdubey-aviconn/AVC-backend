"""Active alarms for the dashboards: one row per issue, from both alarm tables.

``AlarmNotifications`` holds consumption, bypass, operation-hours and meter
reading alarms (per aisle); ``NewAlarmsNotifications`` holds voltage, power
factor and DG alarms (per site and power source). Both keep a row for every
occurrence, so the same issue appears many times. Here every issue becomes
one row: when it started, when it was last seen and how often, with the
site, customer, aisle group, leg, home gateway and the latest details.

The work is a fixed number of queries (grouping happens in the database),
independent of the number of customers or stored alarm rows.
"""

from collections import defaultdict
from datetime import datetime

from django.db.models import Count, Max, Min, Sum

from wareApp.models import (
    AisleSyncRecoveryStatus,
    AlarmNotifications,
    HomeGatewayId,
    NewAlarmsNotifications,
    Site,
)

# Priority labels as the dashboard shows them (0 High, 1 Medium, 2 Low).
PRIORITY_LABELS = {0: "High", 1: "Medium", 2: "Low"}

CONSUMPTION_TYPES = dict(AlarmNotifications._meta.get_field("Alarm_type").flatchoices)
POWER_TYPES = {
    **dict(NewAlarmsNotifications._meta.get_field("alarm_type").flatchoices),
    # Stored by wareApp/dg_fuel/sessions.py but missing from the model choices.
    9: "DG Running Without Load",
}


def _fmt(value):
    return None if value is None else f"{float(value):g}"


def _power_issue(row):
    """Readable details of a voltage / PF / DG alarm row."""
    alarm_type = row.alarm_type
    phases = "/".join(_fmt(v) or "-" for v in (row.r_phase, row.y_phase, row.b_phase))
    if alarm_type in (0, 1):
        return f"R/Y/B voltage {phases} V"
    if alarm_type == 2:
        return f"R/Y/B power factor {phases}"
    if row.fuel_level is not None:
        return f"Fuel {_fmt(row.fuel_level)} L"
    if row.run_hours is not None:
        return f"Run hours {_fmt(row.run_hours)}"
    return POWER_TYPES.get(alarm_type, "")


def active_alarms(site_ids):
    """List of issue rows (dicts) for the given sites, newest activity first."""
    site_ids = list(site_ids)
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

    # ---- AlarmNotifications: per site, aisle/meter and type
    groups = list(
        AlarmNotifications.objects.filter(site_id__in=site_ids, is_active=True)
        .values("site_id", "aisle_group_id", "object_id", "Alarm_type")
        .annotate(
            first_seen=Min("created_time"),
            last_created=Max("created_time"),
            last_seen=Max("last_seen"),
            occurrences=Sum("occurrences"),
            priority=Max("Alarm_priority"),
            latest_id=Max("id"),
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
        aisle = alarm.aisle_group
        last_seen = max(
            d for d in (group["last_created"], group["last_seen"]) if d is not None
        )
        rows.append(
            _row(
                site,
                source="consumption",
                alarm_type=group["Alarm_type"],
                alarm=CONSUMPTION_TYPES.get(
                    group["Alarm_type"], str(group["Alarm_type"])
                ),
                priority=group["priority"],
                first_seen=group["first_seen"],
                last_seen=last_seen,
                occurrences=group["occurrences"] or 1,
                aisle_group_id=aisle.id if aisle else None,
                aisle_group_name=aisle.aisleGroupName if aisle else None,
                leg_id=(aisle.attached_leg_id if aisle else None) or group["object_id"],
                power_source=None,
                home_gateway_id=aisle_gateways.get(group["aisle_group_id"])
                or ", ".join(site_gateways.get(site.id, []))
                or None,
                issue=alarm.to_do or CONSUMPTION_TYPES.get(group["Alarm_type"], ""),
            )
        )

    # ---- NewAlarmsNotifications: per site, type and power source
    groups = list(
        NewAlarmsNotifications.objects.filter(site_id__in=site_ids, is_active=True)
        .values("site_id", "alarm_type", "power_source")
        .annotate(
            first_seen=Min("created"),
            last_seen=Max("created"),
            occurrences=Count("id"),
            priority=Min("alarm_priority"),
            latest_id=Max("id"),
        )
    )
    latest = {
        alarm.id: alarm
        for alarm in NewAlarmsNotifications.objects.filter(
            id__in=[g["latest_id"] for g in groups]
        )
    }
    for group in groups:
        alarm = latest[group["latest_id"]]
        site = sites[group["site_id"]]
        rows.append(
            _row(
                site,
                source="power",
                alarm_type=group["alarm_type"],
                alarm=POWER_TYPES.get(group["alarm_type"], str(group["alarm_type"])),
                priority=group["priority"],
                first_seen=group["first_seen"],
                last_seen=group["last_seen"],
                occurrences=group["occurrences"],
                aisle_group_id=None,
                aisle_group_name=None,
                leg_id=None,
                power_source=group["power_source"],
                home_gateway_id=", ".join(site_gateways.get(site.id, [])) or None,
                issue=_power_issue(alarm),
            )
        )

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
