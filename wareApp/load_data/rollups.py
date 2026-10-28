import logging
import os
import time
from datetime import timedelta
from threading import Lock

from wareApp.models import DailyLoadData, HourlyLoadData, MainsDgLoadData, RawLoadData

_last_rollup_minute_by_site = {}
_last_daily_rollup_hour_by_site = {}
_rollup_locks_by_site = {}
_rollup_schedule_lock = Lock()

logger = logging.getLogger(__name__)


def _lookback_minutes():
    try:
        return max(1, int(os.getenv("LOAD_DATA_ROLLUP_LOOKBACK_MINUTES", "360")))
    except ValueError:
        return 360


def _recheck_minutes():
    """Minutes before the last rolled minute that are checked again (late packets)."""
    try:
        return max(1, int(os.getenv("LOAD_DATA_ROLLUP_RECHECK_MINUTES", "15")))
    except ValueError:
        return 15


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
    minimum = None
    maximum = None
    for reading in readings:
        if reading.load_data is None:
            continue
        if minimum is None or reading.load_data < minimum.load_data:
            minimum = reading
        if maximum is None or reading.load_data > maximum.load_data:
            maximum = reading

    if minimum is None:
        return []

    return sorted((minimum, maximum), key=_epoch_sort_key)


def _materialized_buckets(model, site, window_start, window_end, bucket_function):
    rows = (
        model.objects.filter(
            site=site,
            created__gte=window_start,
            created__lt=window_end,
        )
        .values_list("aisle_group_id", "created")
        .iterator(chunk_size=1000)
    )
    return {
        (aisle_group_id, bucket_function(created))
        for aisle_group_id, created in rows
        if aisle_group_id is not None and created is not None
    }


def _records_for_extrema(model, site, aisle_group, readings):
    extrema = _extrema(readings)
    if not extrema:
        return []

    return [
        model(
            site=site,
            aisle_group=aisle_group,
            load_data=reading.load_data,
            created=reading.created,
            epoch_time=reading.epoch_time,
        )
        for reading in extrema
    ]


def _save_extrema(model, site, aisle_group, readings):
    records = _records_for_extrema(model, site, aisle_group, readings)
    if records:
        model.objects.bulk_create(records)


def _save_batched_extrema(model, site, bucket_extrema, home_gateway_id=None):
    records = []
    for aisle_group, minimum, maximum in bucket_extrema:
        records.extend(
            _records_for_extrema(model, site, aisle_group, (minimum, maximum))
        )

    if records:
        started = time.perf_counter()
        model.objects.bulk_create(records, batch_size=1000)
        duration_ms = (time.perf_counter() - started) * 1000
        aisles = sorted(
            {
                f"{getattr(r.aisle_group, 'aisleGroupName', '?')} (leg {getattr(r.aisle_group, 'attached_leg_id', '?')})"
                for r in records
            }
        )
        created = [r.created for r in records if r.created is not None]
        logger.info(
            "BULK CREATE %s: site=%s home_gateway_id=%s aisle_groups=%s%s rows=%s period=[%s -> %s] duration=%.1f ms",
            model.__name__,
            getattr(site, "pk", None) or site.id,
            home_gateway_id,
            ", ".join(aisles[:5]),
            f" (+{len(aisles) - 5} more)" if len(aisles) > 5 else "",
            len(records),
            min(created) if created else "-",
            max(created) if created else "-",
            duration_ms,
        )


def _extrema_by_bucket(readings, bucket_function):
    grouped = {}
    for reading in readings:
        if (
            reading.aisle_group_id is None
            or reading.created is None
            or reading.load_data is None
        ):
            continue

        bucket_key = (reading.aisle_group_id, bucket_function(reading.created))
        bucket_extrema = grouped.get(bucket_key)
        if bucket_extrema is None:
            grouped[bucket_key] = (reading.aisle_group, reading, reading)
            continue

        aisle_group, minimum, maximum = bucket_extrema
        grouped[bucket_key] = (
            aisle_group,
            reading if reading.load_data < minimum.load_data else minimum,
            reading if reading.load_data > maximum.load_data else maximum,
        )
    return grouped


def roll_up_completed_load_data(
    site, observed_at, roll_up_daily=True, home_gateway_id=None, since=None
):
    """Create missing minute and hour min/max points from raw load readings.

    A gateway packet only finalizes buckets strictly before its own minute. Rechecking
    a window makes the operation idempotent and independent of the gateway's
    reporting interval. ``since`` is the site's last rolled-up minute: the window then
    starts LOAD_DATA_ROLLUP_RECHECK_MINUTES before it (late packets) instead of the
    full LOAD_DATA_ROLLUP_LOOKBACK_MINUTES, which is used only after a restart.
    """
    completed_minute = _minute_bucket(observed_at)
    raw_window_start = completed_minute - timedelta(minutes=_lookback_minutes())
    if since is not None:
        raw_window_start = max(
            raw_window_start, since - timedelta(minutes=_recheck_minutes())
        )
    raw_readings = (
        RawLoadData.objects.filter(
            site=site,
            created__gte=raw_window_start,
            created__lt=completed_minute,
        )
        .select_related("aisle_group")
        .only("aisle_group", "aisle_group__id", "load_data", "created", "epoch_time")
        .order_by("created")
        .iterator(chunk_size=1000)
    )
    hourly_buckets = _materialized_buckets(
        HourlyLoadData,
        site,
        raw_window_start,
        completed_minute,
        _minute_bucket,
    )

    raw_bucket_extrema = [
        bucket_extrema
        for bucket_key, bucket_extrema in _extrema_by_bucket(
            raw_readings, _minute_bucket
        ).items()
        if bucket_key not in hourly_buckets
    ]
    _save_batched_extrema(
        HourlyLoadData, site, raw_bucket_extrema, home_gateway_id=home_gateway_id
    )
    _save_batched_extrema(
        MainsDgLoadData, site, raw_bucket_extrema, home_gateway_id=home_gateway_id
    )

    if not roll_up_daily:
        return

    completed_hour = _hour_bucket(observed_at)
    hourly_window_start = _hour_bucket(raw_window_start)
    hourly_readings = (
        HourlyLoadData.objects.filter(
            site=site,
            created__gte=hourly_window_start,
            created__lt=completed_hour,
        )
        .select_related("aisle_group")
        .only("aisle_group", "aisle_group__id", "load_data", "created", "epoch_time")
        .order_by("aisle_group_id", "created")
        .iterator(chunk_size=1000)
    )
    daily_buckets = _materialized_buckets(
        DailyLoadData,
        site,
        hourly_window_start,
        completed_hour,
        _hour_bucket,
    )

    daily_bucket_extrema = [
        bucket_extrema
        for bucket_key, bucket_extrema in _extrema_by_bucket(
            hourly_readings, _hour_bucket
        ).items()
        if bucket_key not in daily_buckets
    ]
    _save_batched_extrema(
        DailyLoadData, site, daily_bucket_extrema, home_gateway_id=home_gateway_id
    )


def roll_up_load_data_if_due(site, observed_at, home_gateway_id=None):
    """Run a site's catch-up rollup only once for each observed minute."""
    observed_minute = _minute_bucket(observed_at)
    site_key = getattr(site, "pk", None) or site.id

    with _rollup_schedule_lock:
        if _last_rollup_minute_by_site.get(site_key) == observed_minute:
            return False
        site_rollup_lock = _rollup_locks_by_site.setdefault(site_key, Lock())

    with site_rollup_lock:
        with _rollup_schedule_lock:
            if _last_rollup_minute_by_site.get(site_key) == observed_minute:
                return False
            completed_hour = _hour_bucket(observed_at)
            roll_up_daily = (
                _last_daily_rollup_hour_by_site.get(site_key) != completed_hour
            )
            since = _last_rollup_minute_by_site.get(site_key)

        roll_up_completed_load_data(
            site,
            observed_at,
            roll_up_daily=roll_up_daily,
            home_gateway_id=home_gateway_id,
            since=since,
        )
        with _rollup_schedule_lock:
            _last_rollup_minute_by_site[site_key] = observed_minute
            if roll_up_daily:
                _last_daily_rollup_hour_by_site[site_key] = completed_hour
    return True
