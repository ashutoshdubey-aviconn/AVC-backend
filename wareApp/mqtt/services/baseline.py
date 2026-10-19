"""Hourly baseline of an aisle group (Phase C), shared by live and recovery.

Rules (decided 2026-10-20):

* The daily baseline is the ``SiteBaseline`` row whose date range covers the
  day; without one, the latest row for the site and leg.
* EL aisles (an uppercase ``EL`` token in the name, e.g. ``RPC-EL``,
  ``HB-Part-1_EL``, ``EL-GF&F1``) run 24 h: hourly = daily / 24.
* NL aisles use the site's ``nl_operation_hours``: hourly = daily / NL hours,
  the same value for every hour of the day.
* NL aisles of a site without ``nl_operation_hours`` keep the legacy rule:
  hourly = daily / ``SiteBaseline.working_hours``.
* Inactive aisles get no baseline (0), as before.
"""

import logging
import re

from wareApp.mqtt.services import site_cache

logger = logging.getLogger(__name__)

EL_TOKEN = re.compile(r"(?:^|[-_&\s])EL(?=$|[-_&\s])")


def is_emergency_supply(aisle_group_name):
    """True for EL (emergency/UPS) aisles; everything else is NL."""
    return bool(aisle_group_name and EL_TOKEN.search(aisle_group_name))


def baseline_row(site_id, leg_id, day):
    """``(daily_value, working_hours)`` for ``day``, or None when not configured."""
    rows = site_cache.baselines(site_id, leg_id)
    for baseline_from, baseline_to, value, working_hours in rows:
        if baseline_from and baseline_from <= day and (baseline_to is None or day <= baseline_to):
            return value, working_hours
    if rows:
        return rows[0][2], rows[0][3]
    return None


def effective_hours(site, aisle_group, legacy_working_hours):
    """Hours the daily baseline is spread over (see module docstring)."""
    if is_emergency_supply(getattr(aisle_group, "aisleGroupName", "")):
        return 24
    nl_hours = getattr(site, "nl_operation_hours", None)
    if nl_hours:
        return nl_hours
    return legacy_working_hours


def hourly_baseline(site, aisle_group, day):
    """Return ``(hourly_baseline, daily_baseline)`` of an aisle for ``day``."""
    leg_id = aisle_group.attached_leg_id
    row = baseline_row(site.id, leg_id, day)
    if row is None:
        logger.warning("No baseline configured for site %s, leg %s", site.id, leg_id)
        return 0.0, 0.0
    daily_value, working_hours = row
    hours = effective_hours(site, aisle_group, working_hours)
    if not hours:
        logger.warning(
            "No working hours configured for baseline at site %s, leg %s", site.id, leg_id
        )
        return 0.0, daily_value
    return daily_value / hours, daily_value


class BaselineMemo:
    """Hourly/daily baseline of one aisle per day, looked up at most once."""

    def __init__(self, site, aisle_group):
        self.site = site
        self.aisle_group = aisle_group
        self._days = {}

    def for_day(self, day):
        if not getattr(self.aisle_group, "is_active", False):
            return 0.0, 0.0
        if day not in self._days:
            self._days[day] = hourly_baseline(self.site, self.aisle_group, day)
        return self._days[day]
