"""Spread a catch-up hour over the data gap before it (decided 2026-11-16, reworked 2026-11-20).

A gateway service (pymodbus / PostgreSQL / Celery) stops and nothing is saved for some hours; when it
starts again the first reading is "new meter reading - last saved one", so the whole gap's energy
lands in one hour (site 114, 16 Nov 09:00: 43.60 kWh for the 37 hours since 14 Nov 20:00). The
energy is real but booked on the wrong hours and days.

Gap = hours without a row, and hours stored as 0 because the gateway answered ERROR404 (no data on
the gateway; recovery_status.no_data_hours) - never real 0 kWh hours. Proof: the hour before the
gap has real data, and the first hour after it is more than CATCH_UP_FACTOR x the aisle's normal hour.

* ``plan`` (preview, changes nothing): the catch-up hours of a day, per aisle, with the gap, the
  share per hour (kWh / (gap hours + 1)) and the day totals before / after. A catch-up is offered only
  once the aisle is synced again, the hour after it has arrived and recovery of the gap has ended
  (else it is "waiting"). It needs a manual spread (``warnings``) when the share is still more than
  SHARE_WARN_FACTOR x the normal hour (meter jump?) or when the spread days would not match the
  aisle's daily average (DAILY_MATCH).
* ``apply``: every gap hour and the catch-up hour get the share as real readings (no estimated
  mark); hourly and daily of every touched day are recalculated; that day's Consumption Spike alarm
  is closed; a CatchUpSpread row records it with one line per hour (``hours_detail``) and the mode
  (manual / automatic).
* ``undo`` (UNDO_DAYS after the spread): created hours removed, ERROR404 hours back to 0, the
  catch-up hour back to its original kWh, days recalculated.
* ``auto_spread`` (Celery beat): clear cases only, 19:00-11:00 every day and all day on Sunday;
  cases needing a manual spread are e-mailed to the software team once.
* Recovery replies leave spread hours and days alone (``spread_hours`` / ``spread_days``).

See docs/consumption/CATCH_UP_SPREAD.md.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from statistics import median

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum

from wareApp.models import (
    AisleGroup,
    AisleSyncRecoveryStatus,
    AlarmNotifications,
    CatchUpSpread,
    DailySiteReading,
    HourlySiteReading,
    RecoveryMonitor,
    Site,
)
from wareApp.mqtt.consumption import _counted_hours
from wareApp.mqtt.services.baseline import BaselineMemo
from wareApp.mqtt.services.recovery_status import (
    HOURLY_CONSUMPTION,
    OPEN_STATUSES,
    no_data_hours,
    no_data_monitors,
)

logger = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
CATCH_UP_FACTOR = 3  # the catch-up hour is more than 3 x the aisle's normal hour
NORMAL_DAYS = 7  # normal hour = median of the non-zero hours of the 7 days before
LOOKBACK_DAYS = 31  # the gap's start (last real reading) is looked for this far back
SHARE_WARN_FACTOR = 3  # share still > 3 x normal hour: probably not only a catch-up
DAILY_AVERAGE_DAYS = 14  # daily average = median of the non-zero days before the gap
DAILY_MATCH = (0.5, 1.5)  # spread day (share x 24) within this x the daily average: clear case
UNDO_DAYS = 5
SYNCED = ("healthy", "recovered")
EMPTY, NO_DATA, CATCH_UP = "empty", "no_data", "catch_up"


class SpreadError(ValueError):
    """Shown to the user."""


def _hour(at):
    return at.replace(minute=0, second=0, microsecond=0)


def _iso(at):
    return f"{at:%Y-%m-%dT%H:%M:%S}"


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
    previous: datetime  # last real reading before the gap
    normal_hour: float
    missing: list = field(default_factory=list)  # hour starts of the gap
    no_data: set = field(default_factory=set)  # gap hours stored as 0 (ERROR404)
    warnings: list = field(default_factory=list)  # reasons a manual spread is required
    waiting: str = ""  # why it cannot be spread yet
    daily_average: float = None

    @property
    def hours(self):
        return len(self.missing) + 1

    @property
    def share(self):
        return self.kwh / self.hours

    def kind(self, hour):
        return NO_DATA if hour in self.no_data else EMPTY

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
            "empty_hours": len(self.missing) - len(self.no_data),
            "no_data_hours": len(self.no_data),
            "share_kwh": round(self.share, 3),
            "normal_hour_kwh": round(self.normal_hour, 3),
            "spread_day_kwh": round(self.share * 24, 2),
            "daily_average_kwh": round(self.daily_average, 2) if self.daily_average is not None else None,
            "days": [
                {"day": f"{d:%Y/%m/%d}", "before": round(before[d], 2), "after": round(after[d], 2)} for d in days
            ],
            "manual_required": bool(self.warnings),
            "warnings": self.warnings,
        }


def find_catch_ups(site, aisle, day, not_spreadable=None):
    """Catch-up hours of ``aisle`` on ``day`` (oldest first), not yet checked for readiness.

    A big hour with no real reading in the LOOKBACK_DAYS before it cannot be spread (the gap's
    start is unknown); it is added to ``not_spreadable``.
    """
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    leg = str(aisle.attached_leg_id)
    values = dict(
        HourlySiteReading.objects.filter(
            associated_Site=site, leg_id=aisle.attached_leg_id,
            reading_from__gte=start - timedelta(days=LOOKBACK_DAYS), reading_from__lt=end + HOUR,
        ).order_by("reading_from").values_list("reading_from", "unit_consumption")
    )
    values = {_hour(at): kwh or 0.0 for at, kwh in values.items()}
    monitors = no_data_monitors([site.id], start - timedelta(days=LOOKBACK_DAYS), end + HOUR).get((site.id, leg))
    gap_zeros = no_data_hours(monitors, values) if monitors else set()
    real = [(at, kwh) for at, kwh in sorted(values.items()) if at not in gap_zeros]

    def normal_before(at):
        week = [kwh for hour, kwh in real if at - timedelta(days=NORMAL_DAYS) <= hour < at and kwh > 0]
        if not week:  # nothing before it (gap start unknown): judge by the hours after it
            week = [kwh for hour, kwh in real if at < hour <= at + timedelta(days=1) and kwh > 0]
        return median(week) if week else 0.0

    found, previous = [], None
    for at, kwh in real:
        if start <= at < end and kwh and (previous is None or at - previous > HOUR):
            normal = normal_before(previous + HOUR if previous else at)
            if normal > 0 and kwh > CATCH_UP_FACTOR * normal:
                if previous is None:
                    if not_spreadable is not None:
                        not_spreadable.append({
                            "leg_id": leg, "aisle_name": aisle.aisleGroupName,
                            "at": f"{at:%Y/%m/%d %H:%M}", "kwh": round(kwh, 2), "normal_hour_kwh": round(normal, 3),
                            "reason": f"no reading in the {LOOKBACK_DAYS} days before it: the gap's start is unknown",
                        })
                else:
                    missing, step = [], previous + HOUR
                    while step < at:
                        missing.append(step)
                        step += HOUR
                    item = CatchUp(aisle, at, kwh, previous, normal, missing,
                                   no_data={hour for hour in missing if hour in gap_zeros})
                    if (at + HOUR) not in values or (at + HOUR) in gap_zeros:
                        item.waiting = "the hour after the catch-up has not arrived yet"
                    found.append(item)
        previous = at
    return found


def _readiness(site, items):
    """Set ``waiting`` on items whose aisle is not synced again or whose gap is still being recovered."""
    legs = {str(item.aisle.attached_leg_id) for item in items}
    states = dict(
        AisleSyncRecoveryStatus.objects.filter(site=site, leg_id__in=legs, aisle_group__isnull=False)
        .values_list("leg_id", "sync_status")
    )
    open_legs = set(
        RecoveryMonitor.objects.filter(
            site=site, leg_id__in=legs, recovery_type=HOURLY_CONSUMPTION, status__in=OPEN_STATUSES, is_active=True,
        ).values_list("leg_id", flat=True)
    )
    for item in items:
        leg = str(item.aisle.attached_leg_id)
        if item.waiting:
            continue
        if leg in open_legs:
            item.waiting = "recovery of the gap is still running (asked from the gateway)"
        elif states.get(leg) not in (None, *SYNCED):
            item.waiting = f"the aisle is not synced yet ({states[leg].replace('_', ' ')})"


def _daily_average(site, aisle, first_day):
    rows = [
        kwh for kwh in DailySiteReading.objects.filter(
            associated_Site=site, leg_id=aisle.attached_leg_id,
            reading_for__gte=first_day - timedelta(days=DAILY_AVERAGE_DAYS), reading_for__lt=first_day,
        ).values_list("unit_consumption", flat=True)
        if kwh and kwh > 0
    ]
    return median(rows) if rows else None


def _doubts(site, item):
    """Reasons the catch-up needs a manual spread (empty: clear case)."""
    if item.share > SHARE_WARN_FACTOR * item.normal_hour:
        item.warnings.append(
            f"share {item.share:.2f} kWh is still more than {SHARE_WARN_FACTOR} x the normal hour "
            f"({item.normal_hour:.2f}): probably more than a catch-up (meter jump?)"
        )
    item.daily_average = _daily_average(site, item.aisle, item.missing[0].date())
    spread_day = item.share * 24
    if item.daily_average is None:
        item.warnings.append("no daily average before the gap to compare with: manual spread required")
    elif not DAILY_MATCH[0] * item.daily_average <= spread_day <= DAILY_MATCH[1] * item.daily_average:
        item.warnings.append(
            f"a spread day would be {spread_day:.1f} kWh, the aisle's daily average is "
            f"{item.daily_average:.1f} kWh: manual spread required"
        )


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


def _waiting_dict(item):
    return {
        "leg_id": str(item.aisle.attached_leg_id), "aisle_name": item.aisle.aisleGroupName,
        "at": f"{item.at:%Y/%m/%d %H:%M}", "kwh": round(item.kwh, 2), "missing_hours": len(item.missing),
        "reason": item.waiting,
    }


def plan(site, day, legs=None, not_spreadable=None, waiting=None):
    """``[(CatchUp, preview dict)]`` ready to spread for ``site`` on ``day``; changes nothing.

    Big hours that cannot be spread go to ``not_spreadable``; catch-ups not ready yet to ``waiting``.
    """
    day = parse_day(day)
    aisles = AisleGroup.objects.filter(site=site).order_by("id")
    if legs:
        wanted = {str(leg) for leg in legs}
        aisles = [a for a in aisles if str(a.attached_leg_id) in wanted]
        if not aisles:
            raise SpreadError("none of these leg ids belongs to the site")
    found = [item for aisle in aisles for item in find_catch_ups(site, aisle, day, not_spreadable)]
    _readiness(site, found)
    result = []
    for item in found:
        if item.waiting:
            if waiting is not None:
                waiting.append(_waiting_dict(item))
            continue
        _doubts(site, item)
        days = sorted({m.date() for m in item.missing} | {item.at.date()})
        before = _hour_sums(site, item.aisle, days)
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


def _saving(memo, aisle, hour, kwh):
    hourly_baseline, _ = memo.for_day(hour.date())
    return hourly_baseline, (hourly_baseline - kwh) if aisle.is_active else 0.0


def _hourly_row(site, aisle, memo, hour, kwh):
    hourly_baseline, saved = _saving(memo, aisle, hour, kwh)
    return HourlySiteReading(
        associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
        reading_from=hour, reading_to=hour + timedelta(minutes=59, seconds=59),
        unit_consumption=kwh, hourly_baseline_value=hourly_baseline, energy_saved=saved,
        is_visible=True, is_estimated=False,
    )


def apply(site, items, user=None, mode=CatchUpSpread.MANUAL):
    """Spread every planned catch-up (each in its own transaction); returns the CatchUpSpread rows."""
    done = []
    for item, _ in items:
        done.append(_apply_one(site, item, user, mode))
    return done


def _apply_one(site, item, user, mode):
    aisle = item.aisle
    leg = aisle.attached_leg_id
    with transaction.atomic():
        row = (
            HourlySiteReading.objects.select_for_update()
            .filter(associated_Site=site, leg_id=leg, reading_from=item.at).first()
        )
        if row is None or abs((row.unit_consumption or 0.0) - item.kwh) > 1e-6:
            raise SpreadError(f"{aisle.aisleGroupName} {item.at:%d %b %H:%M} changed since the preview")
        stored = {
            r.reading_from: r for r in HourlySiteReading.objects.select_for_update().filter(
                associated_Site=site, leg_id=leg, reading_from__in=item.missing,
            )
        }
        for hour in item.missing:
            current = stored.get(hour)
            if (item.kind(hour) == EMPTY and current is not None) or (
                item.kind(hour) == NO_DATA and (current is None or current.unit_consumption != 0)
            ):
                raise SpreadError(f"{aisle.aisleGroupName} {hour:%d %b %H:%M} changed since the preview")
        memo, share = BaselineMemo(site, aisle), item.share
        HourlySiteReading.objects.bulk_create(
            [_hourly_row(site, aisle, memo, hour, share) for hour in item.missing if item.kind(hour) == EMPTY]
        )
        for hour in item.no_data:
            _, saved = _saving(memo, aisle, hour, share)
            HourlySiteReading.objects.filter(pk=stored[hour].pk).update(
                unit_consumption=share, energy_saved=saved, is_estimated=False,
            )
        _, saved = _saving(memo, aisle, item.at, share)
        HourlySiteReading.objects.filter(pk=row.pk).update(unit_consumption=share, energy_saved=saved,
                                                           is_estimated=False)
        recompute_days(site, aisle, [m.date() for m in item.missing] + [item.at.date()])
        label = "automatic" if mode == CatchUpSpread.AUTOMATIC else "manual"
        AlarmNotifications.objects.filter(
            aisle_group=aisle, Alarm_type=AlarmNotifications.CONSUMPTION_SPIKE,
            created_time=datetime.combine(item.at.date(), time.min), is_active=True,
        ).update(
            is_active=False, off_time=datetime.now(),
            to_do=(f"Spread ({label}): {item.at:%H:%M} {item.kwh:.2f} kWh over {item.hours} h from "
                   f"{item.missing[0]:%d %b %H:%M} (catch-up)")[:200],
        )
        detail = [
            {"at": _iso(hour), "kind": item.kind(hour), "before": 0.0 if item.kind(hour) == NO_DATA else None,
             "after": round(share, 6)}
            for hour in item.missing
        ] + [{"at": _iso(item.at), "kind": CATCH_UP, "before": item.kwh, "after": round(share, 6)}]
        spread = CatchUpSpread.objects.create(
            site=site, aisle_group=aisle, leg_id=str(leg), catch_up_at=item.at,
            original_kwh=item.kwh, gap_from=item.missing[0], hours=item.hours, share_kwh=share, mode=mode,
            applied_by="automatic" if mode == CatchUpSpread.AUTOMATIC else (getattr(user, "username", "") or ""),
            hours_detail=detail,
        )
    logger.warning(
        "Catch-up spread (%s): site=%s leg=%s %s %.2f kWh over %s h from %s (%s empty, %s no data) by %s",
        label, site.id, leg, item.at, item.kwh, item.hours, item.missing[0],
        len(item.missing) - len(item.no_data), len(item.no_data), spread.applied_by or "-",
    )
    return spread


def undo_until(spread):
    return spread.applied_at + timedelta(days=UNDO_DAYS)


def can_undo(spread, now=None):
    return spread.undone_at is None and (now or datetime.now()) <= undo_until(spread)


def undo(spread, user=None, now=None):
    """Reverse one spread exactly (within UNDO_DAYS); returns the number of gap hours put back."""
    if spread.undone_at:
        raise SpreadError("this spread was already undone")
    if not can_undo(spread, now):
        raise SpreadError(f"undo was possible for {UNDO_DAYS} days, until {undo_until(spread):%d %b %Y %H:%M}")
    site, aisle = spread.site, spread.aisle_group
    with transaction.atomic():
        rows = HourlySiteReading.objects.filter(associated_Site=site, leg_id=spread.leg_id)
        memo = BaselineMemo(site, aisle)
        reverted = 0
        if spread.hours_detail:
            for entry in spread.hours_detail:
                hour = datetime.fromisoformat(entry["at"])
                if entry["kind"] == EMPTY:
                    reverted += rows.filter(reading_from=hour).delete()[0]
                else:
                    kwh = entry["before"] or 0.0
                    _, saved = _saving(memo, aisle, hour, kwh)
                    updated = rows.filter(reading_from=hour).update(unit_consumption=kwh, energy_saved=saved,
                                                                    is_estimated=False)
                    reverted += updated if entry["kind"] == NO_DATA else 0
        else:  # spreads made before the per-hour record (16-20 Nov), still marked estimated
            reverted, _ = rows.filter(
                is_estimated=True, reading_from__gte=spread.gap_from, reading_from__lt=spread.catch_up_at,
            ).delete()
            _, saved = _saving(memo, aisle, spread.catch_up_at, spread.original_kwh)
            rows.filter(reading_from=spread.catch_up_at).update(
                unit_consumption=spread.original_kwh, is_estimated=False, energy_saved=saved,
            )
        days, step = [], spread.gap_from
        while step <= spread.catch_up_at:
            days.append(step.date())
            step += HOUR
        recompute_days(site, aisle, days)
        spread.undone_at = datetime.now()
        spread.save(update_fields=["undone_at"])
    logger.warning("Catch-up spread undone: id=%s site=%s leg=%s (%s gap hours put back) by %s",
                   spread.id, site.id, spread.leg_id, reverted, getattr(user, "username", None))
    return reverted


# ------------------------------------------------------------ recovery leaves spreads alone
def _active_spreads(site_id, leg_id, start, end):
    return CatchUpSpread.objects.filter(
        site_id=site_id, leg_id=str(leg_id), undone_at__isnull=True, gap_from__lt=end, catch_up_at__gte=start,
    ).values_list("gap_from", "catch_up_at")


def spread_hours(site_id, leg_id, start, end):
    """Hour starts in [start, end] that belong to a spread (recovery replies must not change them)."""
    hours = set()
    for gap_from, catch_up_at in _active_spreads(site_id, leg_id, start, end + HOUR):
        step = gap_from
        while step <= catch_up_at:
            hours.add(step)
            step += HOUR
    return hours


def spread_days(site_id, leg_id, first_day, last_day):
    """Days in [first_day, last_day] touched by a spread (daily recovery must not change them)."""
    start = datetime.combine(first_day, time.min)
    return {hour.date() for hour in spread_hours(site_id, leg_id, start, datetime.combine(last_day, time.max))
            if first_day <= hour.date() <= last_day}


# ------------------------------------------------------------ automatic spreading
def in_auto_window(now):
    """19:00-11:00 every day (CATCH_UP_AUTO_FROM_HOUR / _UNTIL_HOUR) and all day on Sunday."""
    start = getattr(settings, "CATCH_UP_AUTO_FROM_HOUR", 19)
    until = getattr(settings, "CATCH_UP_AUTO_UNTIL_HOUR", 11)
    return now.weekday() == 6 or now.hour >= start or now.hour < until


def auto_spread(now=None, days_back=None):
    """Spread the clear catch-ups of the last days; e-mail the doubtful ones to the software team once."""
    from wareApp.mqtt.services import alarm_sites
    from wareApp.mqtt.services.notifications import notify
    from wareApp.sendmail import send_software_team_email

    now = now or datetime.now()
    if not in_auto_window(now):
        return "catch-up auto spread: outside 19:00-11:00 (Sunday all day)"
    days_back = getattr(settings, "CATCH_UP_AUTO_DAYS", 3) if days_back is None else days_back
    days = [now.date() - timedelta(days=n) for n in range(days_back - 1, -1, -1)]
    spread = doubtful = failed = 0
    for site in Site.objects.filter(id__in=alarm_sites.monitored_site_ids()).order_by("id"):
        new_doubts = []
        for day in days:
            try:
                items = plan(site, day)
            except Exception:  # one bad site must not stop the others
                logger.exception("Catch-up auto spread: plan failed site=%s day=%s", site.id, day)
                failed += 1
                continue
            for item, preview in items:
                if item.warnings:
                    key = f"catch-up-doubt:{site.id}:{item.aisle.attached_leg_id}:{item.at:%Y%m%d%H}"
                    if cache.add(key, 1, 14 * 24 * 3600):
                        new_doubts.append((item, preview))
                    continue
                try:
                    _apply_one(site, item, None, CatchUpSpread.AUTOMATIC)
                    spread += 1
                except SpreadError as error:
                    logger.warning("Catch-up auto spread skipped: site=%s %s", site.id, error)
        if new_doubts:
            doubtful += len(new_doubts)
            details = [["Catch-up hours", str(len(new_doubts)), False]]
            for item, preview in new_doubts:
                details.append([
                    f"{item.aisle.aisleGroupName} {item.at:%d %b %H:%M}",
                    f"{item.kwh:.2f} kWh after {len(item.missing)} h gap from {item.missing[0]:%d %b %H:%M}"
                    f" - {'; '.join(item.warnings)}",
                    True,
                ])
            details.append(["Action", "Site page -> Spread catch-up -> pick the day, check and spread by hand", False])
            notify(send_software_team_email, "Catch-up spread: manual spread required", site.id, details)
    summary = f"catch-up auto spread: spread={spread} manual_required={doubtful} failed={failed}"
    if spread or doubtful or failed:
        logger.warning(summary)
    return summary
