"""Spread a catch-up hour over the data gap before it (decided 2026-11-16).

When a gateway stores nothing for a while and then comes back, its first hour
carries the whole gap's consumption (site 114, 16 Nov 09:00: 43.60 kWh for the
37 hours since 14 Nov 20:00). The energy is real but booked on the wrong day.
Triggered from the frontend only (``POST /api/catchUpSpread/``,
wareApp/views/catch_up.py):

* ``plan`` (preview, changes nothing): per aisle, the catch-up hours of a day -
  an hour right after a gap that is more than CATCH_UP_FACTOR x the aisle's
  normal hour - with the gap, the share per hour (kWh / (missing hours + 1))
  and the day totals before / after.
* ``apply`` (one transaction per catch-up): the catch-up hour becomes its share
  and the missing hours are created with the same share, all marked
  ``is_estimated``, with the aisle's hourly baseline and saving; the daily
  totals of every touched day are recomputed; that day's Consumption Spike
  alarm is closed with a note; a CatchUpSpread row records it.
* ``undo``: removes the created hours, restores the catch-up hour and
  recomputes the days.

See docs/consumption/CATCH_UP_SPREAD.md.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from statistics import median

from django.db import transaction
from django.db.models import Sum

from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    CatchUpSpread,
    DailySiteReading,
    HourlySiteReading,
)
from wareApp.mqtt.consumption import _counted_hours
from wareApp.mqtt.services.baseline import BaselineMemo

logger = logging.getLogger(__name__)

CATCH_UP_FACTOR = 3  # the catch-up hour is more than 3 x the aisle's normal hour
LOOKBACK_DAYS = 7  # longest gap that can be spread
SHARE_WARN_FACTOR = 3  # share still > 3 x normal hour: probably not only a catch-up


class SpreadError(ValueError):
    """Shown to the user."""


def _hour(at):
    return at.replace(minute=0, second=0, microsecond=0)


def parse_day(value):
    if isinstance(value, date):
        return value
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except (TypeError, ValueError):
            continue
    raise SpreadError(f"day: expected YYYY/MM/DD, got {value!r}")


@dataclass
class CatchUp:
    aisle: AisleGroup
    at: datetime
    kwh: float
    previous: datetime  # last reading before the gap
    normal_hour: float
    missing: list = field(default_factory=list)  # hour starts of the gap
    warnings: list = field(default_factory=list)

    @property
    def hours(self):
        return len(self.missing) + 1

    @property
    def share(self):
        return self.kwh / self.hours

    def as_dict(self, before, after):
        days = sorted({m.date() for m in self.missing} | {self.at.date()})
        return {
            "leg_id": str(self.aisle.attached_leg_id),
            "aisle_name": self.aisle.aisleGroupName,
            "catch_up_at": f"{self.at:%Y/%m/%d %H:%M}",
            "kwh": round(self.kwh, 2),
            "gap_from": f"{self.missing[0]:%Y/%m/%d %H:%M}",
            "gap_to": f"{self.missing[-1]:%Y/%m/%d %H:%M}",
            "missing_hours": len(self.missing),
            "share_kwh": round(self.share, 3),
            "normal_hour_kwh": round(self.normal_hour, 3),
            "days": [
                {"day": f"{d:%Y/%m/%d}", "before": round(before[d], 2), "after": round(after[d], 2)} for d in days
            ],
            "warnings": self.warnings,
        }


def find_catch_ups(site, aisle, day, not_spreadable=None):
    """Catch-up hours of ``aisle`` on ``day`` (oldest first).

    A big first hour with no reading in the LOOKBACK_DAYS before it cannot be
    spread (the gap's start is unknown); it is added to ``not_spreadable``.
    """
    start = datetime.combine(day, time.min)
    rows = list(
        HourlySiteReading.objects.filter(
            associated_Site=site, leg_id=aisle.attached_leg_id,
            reading_from__gte=start - timedelta(days=LOOKBACK_DAYS), reading_from__lt=start + timedelta(days=1),
        ).order_by("reading_from").values_list("reading_from", "unit_consumption")
    )
    positive = [kwh for _, kwh in rows if kwh and kwh > 0]
    found, previous = [], None
    for at, kwh in rows:
        hour = _hour(at)
        if start <= hour and previous is None and kwh and not_spreadable is not None:
            others = [k for k in positive if k != kwh]
            normal = median(others) if others else 0.0
            if normal > 0 and kwh > CATCH_UP_FACTOR * normal:
                not_spreadable.append({
                    "leg_id": str(aisle.attached_leg_id), "aisle_name": aisle.aisleGroupName,
                    "at": f"{hour:%Y/%m/%d %H:%M}", "kwh": round(kwh, 2), "normal_hour_kwh": round(normal, 3),
                    "reason": f"no reading in the {LOOKBACK_DAYS} days before it: the gap's start is unknown",
                })
        if start <= hour and previous is not None and hour - previous > timedelta(hours=1) and kwh:
            others = [k for k in positive if k != kwh]
            normal = median(others) if others else 0.0
            if normal > 0 and kwh > CATCH_UP_FACTOR * normal:
                missing = []
                step = previous + timedelta(hours=1)
                while step < hour:
                    missing.append(step)
                    step += timedelta(hours=1)
                item = CatchUp(aisle, hour, kwh, previous, normal, missing)
                if item.share > SHARE_WARN_FACTOR * normal:
                    item.warnings.append(
                        f"share {item.share:.2f} kWh is still more than {SHARE_WARN_FACTOR} x the normal hour "
                        f"({normal:.2f}): probably more than a catch-up (meter jump?)"
                    )
                found.append(item)
        previous = hour
    return found


def _hour_sums(site, aisle, days):
    """Sum of the aisle's hourly rows per day."""
    sums = defaultdict(float)
    for at, kwh in HourlySiteReading.objects.filter(
        associated_Site=site, leg_id=aisle.attached_leg_id,
        reading_from__gte=datetime.combine(min(days), time.min),
        reading_from__lt=datetime.combine(max(days) + timedelta(days=1), time.min),
    ).values_list("reading_from", "unit_consumption"):
        sums[at.date()] += kwh or 0.0
    return sums


def plan(site, day, legs=None, not_spreadable=None):
    """``[(CatchUp, preview dict)]`` for ``site`` on ``day``; changes nothing.
    Big hours that cannot be spread are added to ``not_spreadable``."""
    day = parse_day(day)
    aisles = AisleGroup.objects.filter(site=site).order_by("id")
    if legs:
        wanted = {str(leg) for leg in legs}
        aisles = [a for a in aisles if str(a.attached_leg_id) in wanted]
        if not aisles:
            raise SpreadError("none of these leg ids belongs to the site")
    result = []
    for aisle in aisles:
        for item in find_catch_ups(site, aisle, day, not_spreadable):
            days = sorted({m.date() for m in item.missing} | {item.at.date()})
            before = _hour_sums(site, aisle, days)
            after = defaultdict(float, before)
            after[item.at.date()] -= item.kwh
            for hour in item.missing + [item.at]:
                after[hour.date()] += item.share
            result.append((item, item.as_dict(before, after)))
    return result


def recompute_days(site, aisle, days):
    """Daily total, baseline and saving of ``days`` from the counted hourly rows."""
    memo = BaselineMemo(site, aisle)
    for day in sorted(set(days)):
        _, daily_baseline = memo.for_day(day)
        total = (
            _counted_hours(site, aisle.attached_leg_id, day, daily_baseline)
            .aggregate(total=Sum("unit_consumption"))["total"] or 0.0
        )
        saved = (daily_baseline - total) if aisle.is_active else 0.0
        rows = DailySiteReading.objects.filter(associated_Site=site, leg_id=aisle.attached_leg_id, reading_for=day)
        if not rows.update(unit_consumption=total, daily_baseline_value=daily_baseline, energy_saved=saved):
            DailySiteReading.objects.create(
                associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id, reading_for=day,
                unit_consumption=total, daily_baseline_value=daily_baseline, energy_saved=saved, is_visible=True,
            )


def _hourly_row(site, aisle, memo, hour, kwh):
    hourly_baseline, _ = memo.for_day(hour.date())
    return HourlySiteReading(
        associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
        reading_from=hour, reading_to=hour + timedelta(minutes=59, seconds=59),
        unit_consumption=kwh, hourly_baseline_value=hourly_baseline,
        energy_saved=(hourly_baseline - kwh) if aisle.is_active else 0.0,
        is_visible=True, is_estimated=True,
    )


def apply(site, items, user=None):
    """Spread every planned catch-up; returns the CatchUpSpread rows."""
    done = []
    for item, _ in items:
        aisle = item.aisle
        with transaction.atomic():
            row = (
                HourlySiteReading.objects.select_for_update()
                .filter(associated_Site=site, leg_id=aisle.attached_leg_id, reading_from=item.at).first()
            )
            if row is None or abs((row.unit_consumption or 0.0) - item.kwh) > 1e-6:
                raise SpreadError(f"{aisle.aisleGroupName} {item.at:%d %b %H:%M} changed since the preview")
            memo = BaselineMemo(site, aisle)
            existing = set(
                HourlySiteReading.objects.filter(
                    associated_Site=site, leg_id=aisle.attached_leg_id, reading_from__in=item.missing,
                ).values_list("reading_from", flat=True)
            )
            HourlySiteReading.objects.bulk_create(
                [_hourly_row(site, aisle, memo, hour, item.share) for hour in item.missing if hour not in existing]
            )
            hourly_baseline, _ = memo.for_day(item.at.date())
            HourlySiteReading.objects.filter(pk=row.pk).update(
                unit_consumption=item.share, is_estimated=True,
                energy_saved=(hourly_baseline - item.share) if aisle.is_active else 0.0,
            )
            recompute_days(site, aisle, [m.date() for m in item.missing] + [item.at.date()])
            AlarmNotifications.objects.filter(
                aisle_group=aisle, Alarm_type=AlarmNotifications.CONSUMPTION_SPIKE,
                created_time=datetime.combine(item.at.date(), time.min), is_active=True,
            ).update(
                is_active=False, off_time=datetime.now(),
                to_do=(f"Spread: {item.at:%H:%M} {item.kwh:.2f} kWh over {item.hours} h from "
                       f"{item.missing[0]:%d %b %H:%M} (catch-up)")[:200],
            )
            done.append(CatchUpSpread.objects.create(
                site=site, aisle_group=aisle, leg_id=str(aisle.attached_leg_id), catch_up_at=item.at,
                original_kwh=item.kwh, gap_from=item.missing[0], hours=item.hours, share_kwh=item.share,
                applied_by=getattr(user, "username", "") or "",
            ))
        logger.warning(
            "Catch-up spread: site=%s leg=%s %s %.2f kWh over %s h from %s by %s",
            site.id, aisle.attached_leg_id, item.at, item.kwh, item.hours, item.missing[0],
            getattr(user, "username", None),
        )
    return done


def undo(spread, user=None):
    """Reverse one spread exactly."""
    if spread.undone_at:
        raise SpreadError("this spread was already undone")
    site, aisle = spread.site, spread.aisle_group
    with transaction.atomic():
        removed, _ = HourlySiteReading.objects.filter(
            associated_Site=site, leg_id=spread.leg_id, is_estimated=True,
            reading_from__gte=spread.gap_from, reading_from__lt=spread.catch_up_at,
        ).delete()
        hourly_baseline, _ = BaselineMemo(site, aisle).for_day(spread.catch_up_at.date())
        HourlySiteReading.objects.filter(
            associated_Site=site, leg_id=spread.leg_id, reading_from=spread.catch_up_at,
        ).update(
            unit_consumption=spread.original_kwh, is_estimated=False,
            energy_saved=(hourly_baseline - spread.original_kwh) if aisle.is_active else 0.0,
        )
        days, step = [], spread.gap_from
        while step <= spread.catch_up_at:
            days.append(step.date())
            step += timedelta(hours=1)
        recompute_days(site, aisle, days)
        spread.undone_at = datetime.now()
        spread.save(update_fields=["undone_at"])
    logger.warning("Catch-up spread undone: id=%s site=%s leg=%s (%s estimated hours removed) by %s",
                   spread.id, site.id, spread.leg_id, removed, getattr(user, "username", None))
    return removed
