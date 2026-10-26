"""Consumption packets processed in batches (bulk writes), same rules as one-by-one.

With ``MQTT_CONSUMPTION_BATCH_SECONDS`` > 0 the queue-1 listener does not start a
task per consumption packet; it parks the packet on the ``mqtt.consumption.batch``
RabbitMQ queue. ``flush_consumption_batch`` (wareApp/tasks.py) runs on that timer,
drains the queue and calls :func:`process_consumption_batch`, which

1. loads, in a few queries, the aisle groups, the hourly rows of the days
   involved and their daily rows,
2. applies every packet in arrival order per aisle *in memory* with exactly
   the rules of ``consumption.handle_consumption_message`` (current hour,
   new hour, first reading, gap -> recovery, daily total, sensor rows),
3. writes all changes with ``bulk_update`` / ``bulk_create`` (one statement
   per table and kind) inside one transaction, and logs BULK CREATE / BULK
   UPDATE lines,
4. runs the day-end alarms and sync-status updates for the aisles touched.

If one aisle fails, its packets become dead letters and the other aisles are
still written. Messages are acknowledged by the caller only after the commit.
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from kombu import Exchange, Queue
from django.db.models import Q

from wareApp.models import (
    AisleGroup,
    DailySiteReading,
    HourlySiteReading,
    SensorAisleUnitConsumption,
)
from wareApp.mqtt import consumption as single
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.log_format import missing_hours
from wareApp.mqtt.services import idempotency
from wareApp.mqtt.services import site_cache as site_config
from wareApp.mqtt.services.cooldown import (
    recovery_request_allowed,
    release_recovery_request,
)
from wareApp.mqtt.services.failures import TRANSIENT_DB_ERRORS, record_dead_letter
from wareApp.mqtt.services.recovery_status import (
    HOURLY_CONSUMPTION,
    RecoveryScope,
    RecoveryStatusService,
)
from wareApp.mqtt.sync_status import mark_sync_healthy

logger = logging.getLogger(__name__)

BULK_BATCH_SIZE = 500
# Packets taken from the queue per flush; the rest wait for the next one.
MAX_PACKETS_PER_FLUSH = 20000

BATCH_QUEUE_NAME = "mqtt.consumption.batch"
BATCH_QUEUE = Queue(
    BATCH_QUEUE_NAME,
    Exchange(BATCH_QUEUE_NAME, type="direct"),
    routing_key=BATCH_QUEUE_NAME,
    durable=True,
)


def batching_enabled():
    return getattr(settings, "MQTT_CONSUMPTION_BATCH_SECONDS", 0) > 0


def enqueue(site_id, gateway_id, payload):
    """Park one consumption packet until the next flush (called by the listener)."""
    from warehouse.celery import app

    with app.producer_or_acquire() as producer:
        producer.publish(
            {"site_id": site_id, "gateway_id": gateway_id, "payload": payload},
            exchange=BATCH_QUEUE.exchange,
            routing_key=BATCH_QUEUE_NAME,
            declare=[BATCH_QUEUE],
            serializer="json",
            delivery_mode=1 if getattr(settings, "MQTT_TRANSIENT_MESSAGES", True) else 2,
            retry=True,
        )


def flush(publish_recovery, limit=MAX_PACKETS_PER_FLUSH):
    """Drain the batch queue, process it, ack after the commit.

    On an exception nothing is acknowledged: the packets go back to the
    queue (in order) and are processed by the next flush.
    """
    from queue import Empty

    from warehouse.celery import app

    with app.connection_for_read() as connection:
        queue = connection.SimpleQueue(BATCH_QUEUE)
        try:
            messages = []
            while len(messages) < limit:
                try:
                    messages.append(queue.get(block=False))
                except Empty:
                    break
            if not messages:
                return "consumption batch: queue empty"
            packets = []
            for message in messages:
                body = message.payload
                if isinstance(body, (bytes, str)):
                    body = json.loads(body)
                packets.append(Packet(int(body["site_id"]), body["gateway_id"], body["payload"]))
            try:
                summary = process_consumption_batch(packets, publish_recovery)
            except BaseException:
                for message in messages:
                    message.requeue()
                raise
            for message in messages:
                message.ack()
            return summary
        finally:
            queue.close()


@dataclass
class Packet:
    site_id: int
    gateway_id: str
    payload: str


@dataclass
class _Parsed:
    packet: Packet
    site: object
    values: dict
    observed_at: datetime
    hour_end: datetime


@dataclass
class _AisleState:
    """Hourly/daily rows of one aisle, changed in memory before the bulk write."""

    site: object
    aisle: object
    leg_id: str
    home_gateway_id: str
    hourly: dict = field(default_factory=lambda: defaultdict(list))  # hour start -> rows
    daily: dict = field(default_factory=lambda: defaultdict(list))  # date -> rows
    dirty_hourly: dict = field(default_factory=dict)  # id(row) -> row
    dirty_daily: dict = field(default_factory=dict)
    new_hourly: list = field(default_factory=list)
    new_daily: list = field(default_factory=list)
    sensor_rows: list = field(default_factory=list)
    alarm_days: set = field(default_factory=set)
    last_stored: datetime = None
    outcomes: list = field(default_factory=list)


def _hour(value):
    return value.replace(minute=0, second=0, microsecond=0)


def _first(rows):
    """``QuerySet.first()`` on an unordered queryset orders by primary key."""
    saved = [r for r in rows if r.pk is not None]
    if saved:
        return min(saved, key=lambda r: r.pk)
    return rows[0] if rows else None


def _parse(packets):
    """Parse packets; diagnostics and bad payloads are handled one by one."""
    parsed, outcomes = [], []
    for packet in packets:
        home_gateway_id = home_gateway_id_for(packet.site_id, packet.gateway_id)
        try:
            site = site_config.site(packet.site_id)
        except Exception:
            logger.warning(
                "Ignoring queued consumption for missing site %s from gateway %s",
                packet.site_id,
                packet.gateway_id,
            )
            outcomes.append(f"skipped: unknown site {packet.site_id}")
            continue
        try:
            if str(packet.payload).strip().startswith("ERROR!!!"):
                logger.warning(
                    "Gateway consumption diagnostic: site=%s home_gateway_id=%s message=%s",
                    packet.site_id,
                    home_gateway_id,
                    packet.payload,
                )
                single._notify_meter_reading_issue(
                    site, packet.site_id, home_gateway_id, packet.payload
                )
                outcomes.append("skipped: gateway diagnostic (meter reading issue stored)")
                continue
            values = single._cap_warehouse_saving_values(
                site, single._parse_consumption_message(packet.payload)
            )
        except TRANSIENT_DB_ERRORS:
            raise
        except Exception as error:
            logger.exception(
                "Queue1 consumption processing failed: site=%s home_gateway_id=%s",
                packet.site_id,
                home_gateway_id,
            )
            record_dead_letter("consumption", packet.site_id, packet.gateway_id, packet.payload, error)
            outcomes.append(f"failed: {type(error).__name__}: {str(error)[:80]} (dead letter)")
            continue
        observed_at = values["observed_date"].replace(
            hour=values["observed_hour"], minute=0, second=0, microsecond=0
        )
        parsed.append(
            _Parsed(packet, site, values, observed_at, observed_at.replace(minute=59, second=59))
        )
    return parsed, outcomes


def _load_states(parsed):
    """One query each for aisle groups, hourly rows and daily rows of the batch."""
    keys = {(p.site.id, str(p.values["aisle_group_id"])) for p in parsed}
    by_site = defaultdict(set)
    for site_id, leg in keys:
        by_site[site_id].add(leg)
    site_filter = Q()
    for site_id, legs in by_site.items():
        site_filter |= Q(site_id=site_id, attached_leg_id__in=legs)
    aisles = {}
    for aisle in AisleGroup.objects.select_for_update().filter(site_filter).order_by("id"):
        aisles.setdefault((aisle.site_id, str(aisle.attached_leg_id)), aisle)

    days = {p.observed_at.date() for p in parsed}
    first_day = datetime.combine(min(days) - timedelta(days=1), datetime.min.time())
    last_day = datetime.combine(max(days) + timedelta(days=1), datetime.min.time())
    reading_filter = Q()
    for site_id, legs in by_site.items():
        reading_filter |= Q(associated_Site_id=site_id, leg_id__in=legs)

    states = {}
    for p in parsed:
        key = (p.site.id, str(p.values["aisle_group_id"]))
        if key not in states and key in aisles:
            states[key] = _AisleState(
                site=p.site,
                aisle=aisles[key],
                leg_id=key[1],
                home_gateway_id=home_gateway_id_for(p.packet.site_id, p.packet.gateway_id),
            )
    for row in HourlySiteReading.objects.filter(
        reading_filter, reading_from__gte=first_day, reading_from__lt=last_day
    ):
        state = states.get((row.associated_Site_id, str(row.leg_id)))
        if state is not None and row.reading_from is not None:
            state.hourly[_hour(row.reading_from)].append(row)
    for row in DailySiteReading.objects.filter(
        reading_filter,
        reading_for__gte=first_day.date(),
        reading_for__lt=last_day.date(),
    ):
        state = states.get((row.associated_Site_id, str(row.leg_id)))
        if state is not None:
            state.daily[row.reading_for].append(row)
    return states


def _last_hourly_entry(state):
    """Newest hourly row of the aisle (database or created in this batch)."""
    stored = (
        HourlySiteReading.objects.filter(associated_Site=state.site, leg_id=state.leg_id)
        .order_by("-reading_from", "-id")
        .first()
    )
    candidates = [r for r in state.new_hourly if r.reading_from is not None]
    if stored is not None:
        candidates.append(stored)
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.reading_from, r.pk or 10**18))


def _as_saved(row):
    """Apply what the model's save() does (CleanReadingMixin) to a new row.

    bulk_create skips save(); the per-packet path creates rows with
    objects.create(), so new rows get the same cleaning here.
    """
    row.clean_reading_values()
    return row


def _day_total(state, day):
    """Sum of the aisle's hourly rows of ``day`` (stored or new in this batch)."""
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    return sum(
        (row.unit_consumption or 0.0)
        for hour, rows in state.hourly.items()
        if day_start <= hour < day_end
        for row in rows
    ) or 0.0


def _stored(state, observed_at):
    if state.last_stored is None or observed_at > state.last_stored:
        state.last_stored = observed_at


def _apply(state, p, publish_recovery):
    """One packet, same branches as handle_consumption_message, rows in memory."""
    site, aisle, values = state.site, state.aisle, p.values
    location_id, gateway_id = p.packet.site_id, p.packet.gateway_id
    leg_id = values["aisle_group_id"]
    observed_at, hour_end = p.observed_at, p.hour_end
    home_gateway_id = state.home_gateway_id
    baselines = single._BaselineMemo(site, aisle, observed_at.date(), home_gateway_id)

    if aisle.on_sensor_power:
        state.sensor_rows.append(
            SensorAisleUnitConsumption(
                associated_Site=site,
                aisle_group=aisle,
                leg_id=leg_id,
                unit_consumption=values["new_unit_consumption"],
                reading_for=observed_at,
            )
        )
        logger.info(
            "Queue1 consumption sensor reading created: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s observed_at=%s",
            location_id, home_gateway_id, leg_id, aisle.aisleGroupName,
            values["new_unit_consumption"], observed_at,
        )

    current = state.hourly.get(_hour(observed_at), [])
    if current:
        for row in current:
            row.unit_consumption = values["current_hour_consumption"]
            if row.pk is not None:
                state.dirty_hourly[id(row)] = row
        logger.info(
            "Queue1 consumption hourly reading updated: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s hour_total=%s observed_at=%s",
            location_id, home_gateway_id, leg_id, aisle.aisleGroupName,
            values["current_hour_consumption"], observed_at,
        )
    else:
        previous = state.hourly.get(_hour(observed_at - timedelta(hours=1)), [])
        previous_record = _first(previous)
        if previous_record:
            updates = {}
            if previous_record.unit_consumption != values["previous_hour_consumption"]:
                updates["unit_consumption"] = values["previous_hour_consumption"]
                previous_record.unit_consumption = values["previous_hour_consumption"]
            hourly_baseline = baselines.hourly
            if aisle.is_active:
                updates["energy_saved"] = hourly_baseline - previous_record.unit_consumption
            if updates:
                for row in previous:
                    for name, value in updates.items():
                        setattr(row, name, value)
                    if row.pk is not None:
                        state.dirty_hourly[id(row)] = row
            row = _as_saved(HourlySiteReading(
                associated_Site=site,
                aisle_group=aisle,
                leg_id=leg_id,
                unit_consumption=values["new_unit_consumption"],
                hourly_baseline_value=hourly_baseline,
                reading_from=observed_at,
                reading_to=hour_end,
                is_visible=True,
            ))
            state.new_hourly.append(row)
            state.hourly[_hour(observed_at)].append(row)
            logger.info(
                "Queue1 consumption hourly reading created: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s hour_total=%s observed_at=%s",
                location_id, home_gateway_id, leg_id, aisle.aisleGroupName,
                values["new_unit_consumption"], values["current_hour_consumption"], observed_at,
            )
        else:
            if not recovery_request_allowed(location_id, "aisle", leg_id):
                logger.info(
                    "Queue1 consumption skipped, gap recovery already requested (cooldown): site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s observed_at=%s",
                    location_id, home_gateway_id, leg_id, aisle.aisleGroupName, observed_at,
                )
                return f"skipped: leg {leg_id} has a gap, recovery already requested (cooldown)"
            last_hourly_entry = _last_hourly_entry(state)
            if last_hourly_entry is not None and not single.stale_history(
                location_id, home_gateway_id, aisle, last_hourly_entry, observed_at
            ):
                request = single._consumption_recovery_request(
                    location_id, gateway_id, leg_id, last_hourly_entry
                )
                if request is None:
                    return f"skipped: leg {leg_id} gap, no recovery request (previous reading incomplete)"
                topic, request_message = request
                decision = RecoveryStatusService(site, home_gateway_id).request_recovery(
                    RecoveryScope.aisle(aisle),
                    HOURLY_CONSUMPTION,
                    last_hourly_entry.reading_from,
                    observed_at,
                    topic,
                    request_message,
                )
                gap = missing_hours(decision.monitor.missing_from, decision.monitor.missing_to)
                if decision.publish:
                    publish_recovery(topic, request_message)
                    logger.warning(
                        "Queue1 consumption recovery requested: site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s missing=%s last_stored_hour=%s observed_at=%s attempt=%s",
                        location_id, home_gateway_id, leg_id, aisle.aisleGroupName, gap,
                        last_hourly_entry.reading_from, observed_at, decision.monitor.attempt,
                    )
                    return f"skipped: leg {leg_id} gap {gap}, recovery requested (attempt {decision.monitor.attempt})"
                logger.warning(
                    "Queue1 consumption skipped, recovery failed for gap: site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s missing=%s attempts=%s",
                    location_id, home_gateway_id, leg_id, aisle.aisleGroupName, gap,
                    decision.monitor.attempt,
                )
                return f"skipped: leg {leg_id} gap {gap}, recovery failed after {decision.monitor.attempt} attempts"

            release_recovery_request(location_id, "aisle", leg_id)
            row = _as_saved(HourlySiteReading(
                associated_Site=site,
                aisle_group=aisle,
                leg_id=leg_id,
                unit_consumption=values["new_unit_consumption"],
                hourly_baseline_value=baselines.hourly,
                reading_from=observed_at,
                reading_to=hour_end,
                is_visible=True,
            ))
            state.new_hourly.append(row)
            state.hourly[_hour(observed_at)].append(row)
            day = _as_saved(DailySiteReading(
                associated_Site=site,
                aisle_group=aisle,
                leg_id=leg_id,
                unit_consumption=values["new_unit_consumption"],
                daily_baseline_value=baselines.daily,
                reading_for=observed_at.date(),
                is_visible=True,
            ))
            state.new_daily.append(day)
            state.daily[observed_at.date()].append(day)
            logger.info(
                "Queue1 consumption hourly and daily readings created: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s hour_total=%s observed_at=%s",
                location_id, home_gateway_id, leg_id, aisle.aisleGroupName,
                values["new_unit_consumption"], values["current_hour_consumption"], observed_at,
            )
            _stored(state, observed_at)
            return f"stored: leg {leg_id} first hourly+daily reading {observed_at:%Y-%m-%d %H:00}"

    # The day's total is the sum of its hourly rows (same as the per-packet path).
    daily_baseline = baselines.daily
    total = _day_total(state, observed_at.date())
    days = state.daily.get(observed_at.date(), [])
    if days:
        for row in days:
            row.unit_consumption = total
            row.energy_saved = daily_baseline - total
            row.daily_baseline_value = daily_baseline
            if row.pk is not None:
                state.dirty_daily[id(row)] = row
    else:
        day = _as_saved(DailySiteReading(
            associated_Site=site,
            aisle_group=aisle,
            leg_id=leg_id,
            unit_consumption=total,
            energy_saved=daily_baseline - total,
            daily_baseline_value=daily_baseline,
            reading_for=observed_at.date(),
            is_visible=True,
        ))
        state.new_daily.append(day)
        state.daily[observed_at.date()].append(day)
        state.alarm_days.add(observed_at.date() - timedelta(days=1))
    logger.info(
        "Queue1 consumption daily reading updated: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s observed_date=%s",
        location_id, home_gateway_id, leg_id, aisle.aisleGroupName,
        values["new_unit_consumption"], observed_at.date(),
    )
    _stored(state, observed_at)
    return f"stored: leg {leg_id} hour {observed_at:%Y-%m-%d %H:00} total={values['current_hour_consumption']}"


def _bulk(model_name, action, rows, states, run):
    """Run one bulk statement and log it with the sites/aisles it covers."""
    if not rows:
        return
    started = time.perf_counter()
    run()
    duration = (time.perf_counter() - started) * 1000
    # Only the aisles whose rows are in this statement.
    by_key = {(s.site.id, s.leg_id): s for s in states}
    written = {(r.associated_Site_id, str(r.leg_id)) for r in rows} & by_key.keys()
    aisles = sorted(
        f"{s.site.id}:{s.aisle.aisleGroupName} (leg {s.leg_id}, gw {s.home_gateway_id})"
        for s in (by_key[key] for key in written)
    )
    periods = [getattr(r, "reading_from", None) or getattr(r, "reading_for", None) for r in rows]
    periods = [p for p in periods if p is not None]
    logger.info(
        "%s %s (consumption batch): rows=%s aisles=%s [%s%s] period=[%s -> %s] duration=%.1f ms",
        action, model_name, len(rows), len(aisles), "; ".join(aisles[:8]),
        f"; +{len(aisles) - 8} more" if len(aisles) > 8 else "",
        min(periods) if periods else "-", max(periods) if periods else "-", duration,
    )


def process_consumption_batch(packets, publish_recovery):
    """Process ``packets`` (list of Packet) in bulk. Returns an outcome summary."""
    started = time.perf_counter()
    claimed, fresh = [], []
    for packet in packets:
        key = idempotency.claim("consumption", packet.site_id, packet.gateway_id, packet.payload)
        if key is None:
            logger.info(
                "Skipped duplicate consumption packet: site=%s gateway=%s",
                packet.site_id, packet.gateway_id,
            )
            continue
        claimed.append(key)
        fresh.append(packet)
    duplicates = len(packets) - len(fresh)
    try:
        with transaction.atomic():
            parsed, outcomes = _parse(fresh)
            states = _load_states(parsed) if parsed else {}
            ok_states = []
            by_aisle = defaultdict(list)
            for p in parsed:
                by_aisle[(p.site.id, str(p.values["aisle_group_id"]))].append(p)
            for key, items in by_aisle.items():
                state = states.get(key)
                if state is None:
                    for p in items:
                        error = ValueError(f"Missing aisle group for leg {p.values['aisle_group_id']}")
                        record_dead_letter("consumption", p.packet.site_id, p.packet.gateway_id, p.packet.payload, error)
                        outcomes.append(f"failed: ValueError: {error} (dead letter)")
                    continue
                try:
                    with transaction.atomic():  # recovery-status writes of this aisle
                        state.outcomes = [_apply(state, p, publish_recovery) for p in items]
                except TRANSIENT_DB_ERRORS:
                    raise
                except Exception as error:
                    logger.exception(
                        "Queue1 consumption batch failed for aisle: site=%s leg_id=%s",
                        key[0], key[1],
                    )
                    for p in items:
                        record_dead_letter("consumption", p.packet.site_id, p.packet.gateway_id, p.packet.payload, error)
                        outcomes.append(f"failed: {type(error).__name__}: {str(error)[:80]} (dead letter)")
                    continue
                ok_states.append(state)
                outcomes += state.outcomes

            dirty_hourly = [r for s in ok_states for r in s.dirty_hourly.values()]
            dirty_daily = [r for s in ok_states for r in s.dirty_daily.values()]
            new_hourly = [r for s in ok_states for r in s.new_hourly]
            new_daily = [r for s in ok_states for r in s.new_daily]
            sensor_rows = [r for s in ok_states for r in s.sensor_rows]
            touched = [s for s in ok_states if s.dirty_hourly or s.new_hourly or s.dirty_daily or s.new_daily]
            _bulk("HourlySiteReading", "BULK UPDATE", dirty_hourly, touched, lambda: HourlySiteReading.objects.bulk_update(
                dirty_hourly, ["unit_consumption", "energy_saved"], batch_size=BULK_BATCH_SIZE))
            _bulk("HourlySiteReading", "BULK CREATE", new_hourly, touched, lambda: HourlySiteReading.objects.bulk_create(
                new_hourly, batch_size=BULK_BATCH_SIZE))
            _bulk("DailySiteReading", "BULK UPDATE", dirty_daily, touched, lambda: DailySiteReading.objects.bulk_update(
                dirty_daily, ["unit_consumption", "energy_saved", "daily_baseline_value"], batch_size=BULK_BATCH_SIZE))
            _bulk("DailySiteReading", "BULK CREATE", new_daily, touched, lambda: DailySiteReading.objects.bulk_create(
                new_daily, batch_size=BULK_BATCH_SIZE))
            _bulk("SensorAisleUnitConsumption", "BULK CREATE", sensor_rows, touched, lambda: SensorAisleUnitConsumption.objects.bulk_create(
                sensor_rows, batch_size=BULK_BATCH_SIZE))

            for state in ok_states:
                for day in sorted(state.alarm_days):
                    yesterday = (
                        DailySiteReading.objects.filter(
                            associated_Site=state.site, leg_id=state.leg_id, reading_for=day
                        ).order_by("pk").first()
                    )
                    if yesterday:
                        single._consumption_alarms(state.site, state.aisle, yesterday)
                if state.last_stored is not None:
                    mark_sync_healthy(state.site, state.home_gateway_id, state.aisle, state.last_stored)
    except BaseException:
        for key in claimed:
            idempotency.release(key)
        raise

    counts = defaultdict(int)
    for outcome in outcomes:
        counts[outcome.split(":")[0]] += 1
    summary = (
        f"consumption batch: {len(packets)} packets, stored={counts['stored']} "
        f"skipped={counts['skipped'] + duplicates} (duplicates {duplicates}) failed={counts['failed']} "
        f"aisles={len(by_aisle) if fresh else 0} in {(time.perf_counter() - started) * 1000:.0f} ms"
    )
    logger.info(summary)
    return summary
