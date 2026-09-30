from collections import defaultdict
from datetime import timedelta
import os
from threading import Lock

from wareApp.models import DailyLoadData, HourlyLoadData, MainsDgLoadData, RawLoadData

_last_rollup_minute_by_site = {}
_rollup_schedule_lock = Lock()


def _lookback_minutes():
    try:
        return max(1, int(os.getenv("LOAD_DATA_ROLLUP_LOOKBACK_MINUTES", "360")))
    except ValueError:
        return 360


def _minute_bucket(value):
    return value.replace(second=0, microsecond=0)


def _hour_bucket(value):
    return value.replace(minute=0, second=0, microsecond=0)


def _epoch_sort_key(reading):
    try:
        return int(reading.epoch_time)
    except (TypeError, ValueError):
        return reading.created.timestamp()


def _extrema(readings):
    valid_readings = [reading for reading in readings if reading.load_data is not None]
    if not valid_readings:
        return []

    minimum = min(valid_readings, key=lambda reading: reading.load_data)
    maximum = max(valid_readings, key=lambda reading: reading.load_data)
    return sorted((minimum, maximum), key=_epoch_sort_key)


def _bucket_has_rows(model, site, aisle_group, bucket_start, bucket_end):
    return model.objects.filter(
        site=site,
        aisle_group=aisle_group,
        created__gte=bucket_start,
        created__lt=bucket_end,
    ).exists()


def _save_extrema(model, site, aisle_group, readings):
    for reading in _extrema(readings):
        model.objects.create(
            site=site,
            aisle_group=aisle_group,
            load_data=reading.load_data,
            created=reading.created,
            epoch_time=reading.epoch_time,
        )


def _group_by_bucket(readings, bucket_function):
    grouped = defaultdict(list)
    for reading in readings:
        if reading.aisle_group_id is not None and reading.created is not None:
            grouped[(reading.aisle_group_id, bucket_function(reading.created))].append(
                reading
            )
    return grouped


def roll_up_completed_load_data(site, observed_at):
    """Create missing minute and hour min/max points from raw load readings.

    A gateway packet only finalizes buckets strictly before its own minute. Rechecking
    the configurable lookback makes the operation idempotent and independent of the
    gateway's reporting interval.
    """
    completed_minute = _minute_bucket(observed_at)
    raw_window_start = completed_minute - timedelta(minutes=_lookback_minutes())
    raw_readings = (
        RawLoadData.objects.filter(
            site=site,
            created__gte=raw_window_start,
            created__lt=completed_minute,
        )
        .select_related("aisle_group")
        .order_by("aisle_group_id", "created")
    )

    for (_, bucket_start), readings in _group_by_bucket(
        raw_readings, _minute_bucket
    ).items():
        aisle_group = readings[0].aisle_group
        bucket_end = bucket_start + timedelta(minutes=1)
        if _bucket_has_rows(
            HourlyLoadData, site, aisle_group, bucket_start, bucket_end
        ):
            continue

        _save_extrema(HourlyLoadData, site, aisle_group, readings)
        _save_extrema(MainsDgLoadData, site, aisle_group, readings)

    completed_hour = _hour_bucket(observed_at)
    hourly_window_start = _hour_bucket(raw_window_start)
    hourly_readings = (
        HourlyLoadData.objects.filter(
            site=site,
            created__gte=hourly_window_start,
            created__lt=completed_hour,
        )
        .select_related("aisle_group")
        .order_by("aisle_group_id", "created")
    )

    for (_, bucket_start), readings in _group_by_bucket(
        hourly_readings, _hour_bucket
    ).items():
        aisle_group = readings[0].aisle_group
        bucket_end = bucket_start + timedelta(hours=1)
        if _bucket_has_rows(DailyLoadData, site, aisle_group, bucket_start, bucket_end):
            continue

        _save_extrema(DailyLoadData, site, aisle_group, readings)


def roll_up_load_data_if_due(site, observed_at):
    """Run a site's catch-up rollup only once for each observed minute."""
    observed_minute = _minute_bucket(observed_at)
    site_key = getattr(site, "pk", None) or site.id

    with _rollup_schedule_lock:
        if _last_rollup_minute_by_site.get(site_key) == observed_minute:
            return False

        roll_up_completed_load_data(site, observed_at)
        _last_rollup_minute_by_site[site_key] = observed_minute
        return True
