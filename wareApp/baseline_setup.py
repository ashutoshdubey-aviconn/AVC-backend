"""Automatic baseline setup of a site (decided 2026-11-05).

Replaces the manual steps (average the sample days per aisle, Set Baseline per
aisle, re-enter the value for every day since, tick AisleGroup.is_active, set
Site.is_live / baseline_date, fill in the site manager). One API call
(``POST /api/baselineSetup/``, wareApp/views/baseline.py):

1. ``plan``: per aisle, the daily consumption of each sample day and their
   average = the baseline. Days without data or with 0 kWh are left out of
   the average and listed as warnings; a value can be overridden per aisle.
   Changes nothing (preview).
2. ``apply`` (one transaction): SiteBaseline rows from ``effective_from``
   (an open previous baseline is closed the day before), the aisles active,
   the site live with its baseline date, site manager details when given, and
   ``backfill``.
3. ``backfill``: from ``effective_from`` to now, every daily row gets the
   baseline and saving (= baseline - consumption) and every hourly row its
   hourly baseline (services/baseline.py rule) and saving. Run again ~6 min
   later by a Celery task, because workers may still hold the old baseline in
   their cache (site_cache, CONFIG_CACHE_TTL).

Days before ``effective_from`` are not touched; no alarm or e-mail is raised
for backfilled days. See docs/consumption/BASELINE_SETUP.md.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db import transaction

from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    DailySiteReading,
    HourlySiteReading,
    SiteBaseline,
)
from wareApp.mqtt.services.baseline import effective_hours

logger = logging.getLogger(__name__)

MAX_SAMPLE_DAYS = 31
BATCH = 2000


class BaselineSetupError(ValueError):
    """The request cannot be planned or applied (message is shown to the user)."""


def parse_day(value, name):
    if isinstance(value, date):
        return value
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except (TypeError, ValueError):
            continue
    raise BaselineSetupError(f"{name}: expected YYYY/MM/DD, got {value!r}")


@dataclass
class AislePlan:
    aisle: AisleGroup
    days: dict = field(default_factory=dict)  # day -> kWh or None (no row)
    average: float = None
    override: float = None
    warnings: list = field(default_factory=list)
    working_hours: float = 24

    @property
    def value(self):
        return self.override if self.override is not None else self.average

    def as_dict(self):
        return {
            "leg_id": str(self.aisle.attached_leg_id),
            "aisle_name": self.aisle.aisleGroupName,
            "is_active": self.aisle.is_active,
            "days": {f"{day:%Y/%m/%d}": (None if kwh is None else round(kwh, 2)) for day, kwh in self.days.items()},
            "average": None if self.average is None else round(self.average, 2),
            "override": self.override,
            "baseline": None if self.value is None else round(self.value, 2),
            "warnings": self.warnings,
        }


@dataclass
class Plan:
    site: object
    sample_from: date
    sample_to: date
    effective_from: date
    aisles: list
    errors: list = field(default_factory=list)

    def as_dict(self):
        return {
            "site_id": self.site.id,
            "site_name": self.site.site_name,
            "sample_from": f"{self.sample_from:%Y/%m/%d}",
            "sample_to": f"{self.sample_to:%Y/%m/%d}",
            "effective_from": f"{self.effective_from:%Y/%m/%d}",
            "aisles": [aisle.as_dict() for aisle in self.aisles],
            "site_total": round(sum(a.value for a in self.aisles if a.value is not None), 2),
            "errors": self.errors,
        }


def plan(site, sample_from, sample_to, effective_from=None, legs=None, overrides=None, today=None):
    """Work out the baseline per aisle; changes nothing."""
    today = today or date.today()
    sample_from = parse_day(sample_from, "sample_from")
    sample_to = parse_day(sample_to, "sample_to")
    if sample_to < sample_from:
        raise BaselineSetupError("sample_to is before sample_from")
    if (sample_to - sample_from).days + 1 > MAX_SAMPLE_DAYS:
        raise BaselineSetupError(f"at most {MAX_SAMPLE_DAYS} sample days")
    if sample_to >= today:
        raise BaselineSetupError("sample days must be complete days before today")
    effective_from = parse_day(effective_from, "effective_from") if effective_from else sample_to + timedelta(days=1)
    if effective_from > today:
        raise BaselineSetupError("effective_from cannot be in the future")
    overrides = {str(k): float(v) for k, v in (overrides or {}).items()}

    aisles = list(AisleGroup.objects.filter(site=site).order_by("id"))
    if legs:
        wanted = {str(leg) for leg in legs}
        unknown = wanted - {str(a.attached_leg_id) for a in aisles}
        if unknown:
            raise BaselineSetupError(f"unknown leg_id(s) for this site: {', '.join(sorted(unknown))}")
        aisles = [a for a in aisles if str(a.attached_leg_id) in wanted]
    if not aisles:
        raise BaselineSetupError("the site has no aisle groups")
    unknown = set(overrides) - {str(a.attached_leg_id) for a in aisles}
    if unknown:
        raise BaselineSetupError(f"overrides for unknown leg_id(s): {', '.join(sorted(unknown))}")

    sample_days = [sample_from + timedelta(days=n) for n in range((sample_to - sample_from).days + 1)]
    legs_of = {str(a.attached_leg_id): a for a in aisles}
    daily = {
        (str(leg), day): kwh
        for leg, day, kwh in DailySiteReading.objects.filter(
            associated_Site=site, leg_id__in=legs_of, reading_for__gte=sample_from, reading_for__lte=sample_to,
        ).values_list("leg_id", "reading_for", "unit_consumption")
    }
    hours = {}
    for leg, at in HourlySiteReading.objects.filter(
        associated_Site=site, leg_id__in=legs_of,
        reading_from__gte=datetime.combine(sample_from, time.min),
        reading_from__lt=datetime.combine(sample_to + timedelta(days=1), time.min),
    ).values_list("leg_id", "reading_from"):
        hours[(str(leg), at.date())] = hours.get((str(leg), at.date()), 0) + 1
    meter_issues = set(
        (str(leg), created.date())
        for leg, created in AlarmNotifications.objects.filter(
            site_id=site, Alarm_type=AlarmNotifications.METER_READING_ISSUE,
            aisle_group__in=aisles,
            created_time__gte=datetime.combine(sample_from, time.min),
            created_time__lt=datetime.combine(sample_to + timedelta(days=1), time.min),
        ).values_list("aisle_group__attached_leg_id", "created_time")
    )
    later = {
        str(leg): baseline_from
        for leg, baseline_from in SiteBaseline.objects.filter(
            associated_site_id=site, leg_id__in=legs_of, baseline_from__gt=effective_from,
        ).values_list("leg_id", "baseline_from")
    }

    result = Plan(site, sample_from, sample_to, effective_from, [])
    for leg, aisle in legs_of.items():
        item = AislePlan(aisle, override=overrides.get(leg))
        previous = (
            SiteBaseline.objects.filter(associated_site_id=site, leg_id=leg)
            .order_by("-baseline_from", "-id").values_list("working_hours", flat=True).first()
        )
        item.working_hours = previous or 24
        used = []
        for day in sample_days:
            kwh = daily.get((leg, day))
            item.days[day] = kwh
            if kwh is None:
                item.warnings.append(f"{day:%d %b}: no data (left out)")
                continue
            if kwh <= 0:
                item.warnings.append(f"{day:%d %b}: 0 kWh (left out)")
                continue
            used.append(kwh)
            if hours.get((leg, day), 0) < 24:
                item.warnings.append(f"{day:%d %b}: only {hours.get((leg, day), 0)} of 24 hours stored")
            if (leg, day) in meter_issues:
                item.warnings.append(f"{day:%d %b}: Meter Reading Issue that day")
        item.average = sum(used) / len(used) if used else None
        if item.value is None:
            result.errors.append(f"{aisle.aisleGroupName} ({leg}): no usable sample day - give an override")
        if leg in later:
            result.errors.append(
                f"{aisle.aisleGroupName} ({leg}): a later baseline starts {later[leg]:%Y/%m/%d}; "
                "choose an effective_from on or after it"
            )
        result.aisles.append(item)
    return result


def _set_baseline(site, aisle, value, working_hours, effective_from):
    leg = str(aisle.attached_leg_id)
    rows = SiteBaseline.objects.filter(associated_site_id=site, leg_id=leg)
    same_day = rows.filter(baseline_from=effective_from).order_by("-id").first()
    if same_day is not None:
        same_day.baseline_value = value
        same_day.baseline_to = None
        same_day.aisle_group = aisle
        same_day.save()
        return "updated"
    for open_row in rows.filter(baseline_from__lt=effective_from).exclude(baseline_to__lt=effective_from):
        open_row.baseline_to = effective_from - timedelta(days=1)
        open_row.save()  # save(): drops the cached baselines (site_cache signal)
    SiteBaseline.objects.create(
        associated_site_id=site, aisle_group=aisle, leg_id=leg, baseline_value=value,
        working_hours=working_hours, baseline_from=effective_from,
    )
    return "created"


def backfill(site, effective_from, legs=None, until=None):
    """Baseline and saving of the daily and hourly rows from ``effective_from``.

    Uses the SiteBaseline rows directly (not the cache), so it is right inside
    the apply transaction. Returns ``{"daily": n, "hourly": n}`` rows changed.
    """
    effective_from = parse_day(effective_from, "effective_from")
    until = until or datetime.now()
    aisles = AisleGroup.objects.filter(site=site)
    if legs:
        aisles = aisles.filter(attached_leg_id__in=[str(leg) for leg in legs])
    changed = {"daily": 0, "hourly": 0}
    for aisle in aisles:
        leg = str(aisle.attached_leg_id)
        periods = list(
            SiteBaseline.objects.filter(associated_site_id=site, leg_id=leg)
            .exclude(baseline_to__lt=effective_from)
            .order_by("baseline_from").values_list("baseline_from", "baseline_to", "baseline_value", "working_hours")
        )
        if not periods:
            continue

        def daily_value(day):
            for start, end, value, working_hours in reversed(periods):
                if start and start <= day and (end is None or day <= end):
                    return value, working_hours
            return None

        dirty = []
        for row in DailySiteReading.objects.filter(
            associated_Site=site, leg_id=leg, reading_for__gte=effective_from, reading_for__lte=until.date(),
        ):
            found = daily_value(row.reading_for)
            if found is None:
                continue
            baseline = found[0] if aisle.is_active else 0.0
            saved = (baseline - (row.unit_consumption or 0.0)) if aisle.is_active else 0.0
            if row.daily_baseline_value != baseline or row.energy_saved != saved:
                row.daily_baseline_value, row.energy_saved = baseline, saved
                dirty.append(row)
        DailySiteReading.objects.bulk_update(dirty, ["daily_baseline_value", "energy_saved"], batch_size=BATCH)
        changed["daily"] += len(dirty)

        dirty = []
        for row in HourlySiteReading.objects.filter(
            associated_Site=site, leg_id=leg,
            reading_from__gte=datetime.combine(effective_from, time.min), reading_from__lt=until,
        ).only("id", "reading_from", "unit_consumption", "hourly_baseline_value", "energy_saved").iterator(
            chunk_size=BATCH
        ):
            found = daily_value(row.reading_from.date())
            if found is None:
                continue
            hours = effective_hours(site, aisle, found[1]) or 24
            hourly = (found[0] / hours) if aisle.is_active else 0.0
            saved = (hourly - (row.unit_consumption or 0.0)) if aisle.is_active else 0.0
            if row.hourly_baseline_value != hourly or row.energy_saved != saved:
                row.hourly_baseline_value, row.energy_saved = hourly, saved
                dirty.append(row)
        HourlySiteReading.objects.bulk_update(dirty, ["hourly_baseline_value", "energy_saved"], batch_size=BATCH)
        changed["hourly"] += len(dirty)
    return changed


def apply(site, the_plan, manager=None, user=None, schedule_refresh=True):
    """Write the plan (one transaction); returns a summary dict."""
    if the_plan.errors:
        raise BaselineSetupError("; ".join(the_plan.errors))
    manager = manager or {}
    with transaction.atomic():
        baselines = {}
        for item in the_plan.aisles:
            aisle = item.aisle
            baselines[str(aisle.attached_leg_id)] = _set_baseline(
                site, aisle, item.value, item.working_hours, the_plan.effective_from
            )
            if not aisle.is_active:
                aisle.is_active = True
                aisle.save(update_fields=["is_active"])
        site.is_live = True
        if site.live_date is None:
            site.live_date = datetime.now()
        site.baseline_date = datetime.combine(the_plan.effective_from, time.min)
        for key, attr in (("name", "site_manager"), ("contact", "site_manager_contact"), ("email", "site_manager_email")):
            if manager.get(key):
                setattr(site, attr, str(manager[key]).strip())
        site.save()
        legs = [str(item.aisle.attached_leg_id) for item in the_plan.aisles]
        changed = backfill(site, the_plan.effective_from, legs)
        if schedule_refresh:
            transaction.on_commit(lambda: _schedule_refresh(site.id, the_plan.effective_from, legs))
    logger.warning(
        "Baseline setup applied: site=%s user=%s effective_from=%s sample=%s..%s values=%s backfill=%s",
        site.id, getattr(user, "username", None), the_plan.effective_from, the_plan.sample_from,
        the_plan.sample_to,
        {item.aisle.aisleGroupName: round(item.value, 2) for item in the_plan.aisles}, changed,
    )
    return {"baselines": baselines, "backfill": changed, "site": {
        "is_live": site.is_live, "live_date": site.live_date, "baseline_date": site.baseline_date,
        "site_manager": site.site_manager, "site_manager_contact": site.site_manager_contact,
        "site_manager_email": site.site_manager_email,
    }}


def _schedule_refresh(site_id, effective_from, legs):
    from wareApp.tasks import refresh_baseline_backfill

    # Workers may cache the old baseline for up to CONFIG_CACHE_TTL (300 s).
    refresh_baseline_backfill.apply_async(args=[site_id, f"{effective_from:%Y-%m-%d}", legs], countdown=360)
