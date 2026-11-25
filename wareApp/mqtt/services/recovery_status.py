"""Recovery request / response lifecycle and the per-aisle sync status.

Every gap gets one ``RecoveryMonitor`` row (the history) and the matching
``AisleSyncRecoveryStatus`` row (the current state) is moved through::

    healthy --gap--> recovery_requested --payload--> recovery_received
        --rows applied + every missing hour present--> recovered --next packet--> healthy
    recovery_requested --cooldown, no answer--> retried (attempt + 1)
    recovery_requested --max attempts--> failed
    healthy --no packets (sweep)--> late --> missing

Both transports use this service: the MQTT recovery handlers and the HTTP
recovery upload (``wareApp/recovery/processor.py``). All writes happen inside
the caller's transaction, so status and data commit together.

ERROR404 slots mean the gateway has no data for that hour (it was down). They
are stored as 0 (agreed rule), count as resolved during verification, and set
``has_data_loss`` on the status. The first hour with data after them carries
the whole outage's consumption (the meter's cumulative difference) and is
recorded as ``RecoveryMonitor.catch_up_at`` so alarms can skip it.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from wareApp.models import HourlySiteReading, RecoveryMonitor, SupplyLoadTimeShare
from wareApp.mqtt.log_format import missing_hours
from wareApp.mqtt.sync_status import upsert_status

logger = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
HOURLY_CONSUMPTION = "hourly_consumption"
DAILY_CONSUMPTION = "daily_consumption"
LOAD_RUNTIME = "load_runtime"
# A request is "open" until it is verified or failed; a partial answer
# (applied but not verified) is retried like an unanswered one.
OPEN_STATUSES = ("requested", "timeout", "response_received", "applied")
MAX_PAYLOAD_CHARS = 20000


@dataclass(frozen=True)
class RecoveryScope:
    """What a recovery is about: an aisle group (consumption) or a power source.

    Origin: Ashu
    """

    aisle_group: object = None
    power_source: int = None

    @classmethod
    def aisle(cls, aisle_group):
        """Recovery scope for one aisle (consumption).

        Origin: Ashu
        """
        return cls(aisle_group=aisle_group)

    @classmethod
    def source(cls, power_source):
        """Recovery scope for one power source (run time).

        Origin: Ashu
        """
        return cls(power_source=int(power_source))

    @property
    def label(self):
        """``leg_id=735 aisle_group_name=HB_RA`` or ``source=1`` for log lines.

        Origin: Ashu
        """
        if self.aisle_group is None:
            return f"source={self.power_source}"
        return (
            f"leg_id={self.leg_id} "
            f"aisle_group_name={getattr(self.aisle_group, 'aisleGroupName', '')}"
        )

    @property
    def leg_id(self):
        """Leg id of the aisle in scope, or None for a power source.

        Origin: Ashu
        """
        if self.aisle_group is None:
            return None
        return str(self.aisle_group.attached_leg_id or "")

    def monitor_filter(self):
        """Filter for RecoveryMonitor rows of this scope.

        Origin: Ashu
        """
        if self.aisle_group is not None:
            return {"leg_id": self.leg_id}
        return {"power_source": self.power_source}

    def status_kwargs(self):
        """Fields that identify the AisleSyncRecoveryStatus row of this scope.

        Origin: Ashu
        """
        return {"aisle_group": self.aisle_group, "power_source": self.power_source}


@dataclass(frozen=True)
class RecoveryDecision:
    """Whether a recovery request should be published now, with its RecoveryMonitor row.

    Origin: Ashu
    """
    publish: bool
    monitor: RecoveryMonitor = None


@dataclass(frozen=True)
class RecoverySlot:
    """One hour (or day) of a recovery payload.

    Origin: Ashu
    """

    start: object
    is_error: bool


class RecoveryStatusService:
    """Keeps recovery requests and the per-aisle sync state of one gateway: when to ask again,
    attempts, timeouts, success.

    Origin: Ashu
    """
    def __init__(self, site, home_gateway_id, now=None):
        """Service for one site and gateway at a given time.

        Origin: Ashu
        """
        self.site = site
        self.home_gateway_id = str(home_gateway_id)
        self.now = now or timezone.now()

    # ------------------------------------------------------------ settings
    @staticmethod
    def max_attempts():
        """How many times a recovery is asked before it is marked failed (MQTT_RECOVERY_MAX_ATTEMPTS,
        3).

        Origin: Ashu
        """
        return getattr(settings, "MQTT_RECOVERY_MAX_ATTEMPTS", 3)

    @staticmethod
    def failed_retry_after():
        """How long after a failed recovery it may be tried again (MQTT_RECOVERY_FAILED_RETRY_SECONDS,
        6 h).

        Origin: Ashu
        """
        return timedelta(
            seconds=getattr(settings, "MQTT_RECOVERY_FAILED_RETRY_SECONDS", 6 * 3600)
        )

    # ------------------------------------------------------------ helpers
    # Newest first, written as DESC NULLS LAST (requested_at is never null, so
    # the order is the same): plain DESC let PostgreSQL walk the
    # (requested_at, is_active) index backwards through every monitor when the
    # scope had no match (~8 ms); this uses the site/scope index (< 0.3 ms).
    NEWEST_FIRST = (F("requested_at").desc(nulls_last=True), "-id")

    def _latest_monitor(self, scope, recovery_type):
        """Newest recovery request of a scope and recovery type.

        Origin: Ashu
        """
        return (
            RecoveryMonitor.objects.filter(
                site=self.site, recovery_type=recovery_type, **scope.monitor_filter()
            )
            .order_by(*self.NEWEST_FIRST)
            .first()
        )

    def _write_status(self, scope, **fields):
        """Updates (or creates) the sync status row of a scope.

        Origin: Ashu
        """
        upsert_status(self.site, self.home_gateway_id, fields, **scope.status_kwargs())

    # ------------------------------------------------------------ requests
    def request_recovery(self, scope, recovery_type, last_stored_slot, observed_slot, topic, payload):
        """Record a gap and decide whether to publish the sync request.

        ``last_stored_slot`` is the start of the newest stored hour and
        ``observed_slot`` the hour of the packet that revealed the gap; the
        missing hours are ``[last_stored_slot + 1h, observed_slot)``.

        Origin: Ashu
        """
        missing_from = last_stored_slot + HOUR
        missing_to = observed_slot
        expected_slots = max(int((missing_to - missing_from) / HOUR), 1)
        monitor = self._latest_monitor(scope, recovery_type)

        if monitor is not None and monitor.status in OPEN_STATUSES:
            if monitor.attempt >= self.max_attempts():
                monitor.status = "failed"
                monitor.failed_reason = (
                    f"No complete recovery after {monitor.attempt} attempts"
                )
                monitor.is_active = False
                monitor.save(update_fields=["status", "failed_reason", "is_active"])
                self._write_status(
                    scope,
                    sync_status="failed",
                    is_sync_gone=True,
                    recovery_requested=False,
                    last_error=monitor.failed_reason,
                    recovery_monitor=monitor,
                )
                logger.warning(
                    "Recovery failed, no more requests for %s: site=%s home_gateway_id=%s %s missing=%s attempts=%s",
                    self.failed_retry_after(),
                    self.site.pk,
                    self.home_gateway_id,
                    scope.label,
                    missing_hours(monitor.missing_from, monitor.missing_to),
                    monitor.attempt,
                )
                return RecoveryDecision(publish=False, monitor=monitor)
            monitor.attempt += 1
            monitor.status = "requested"
            monitor.requested_at = self.now
            monitor.missing_from = min(monitor.missing_from, missing_from)
            monitor.missing_to = max(monitor.missing_to or missing_to, missing_to)
            monitor.expected_slots = max(
                int((monitor.missing_to - monitor.missing_from) / HOUR), 1
            )
            monitor.mqtt_request_topic = topic
            monitor.mqtt_request_payload = payload
            monitor.save()
        elif (
            monitor is not None
            and monitor.status == "failed"
            and self.now - monitor.requested_at < self.failed_retry_after()
        ):
            return RecoveryDecision(publish=False, monitor=monitor)
        else:
            monitor = RecoveryMonitor.objects.create(
                site=self.site,
                gateway_id=self.home_gateway_id,
                aisle_group=scope.aisle_group,
                leg_id=scope.leg_id,
                power_source=scope.power_source,
                recovery_type=recovery_type,
                status="requested",
                missing_from=missing_from,
                missing_to=missing_to,
                expected_slots=expected_slots,
                mqtt_request_topic=topic,
                mqtt_request_payload=payload,
                requested_at=self.now,
            )

        self._write_status(
            scope,
            sync_status="recovery_requested",
            is_sync_gone=True,
            recovery_requested=True,
            recovery_received=False,
            last_recovery_requested_at=self.now,
            expected_from=monitor.missing_from,
            expected_to=monitor.missing_to,
            missing_slots=monitor.expected_slots,
            recovery_monitor=monitor,
        )
        return RecoveryDecision(publish=True, monitor=monitor)

    # ------------------------------------------------------------ responses
    def record_response(self, scope, recovery_type, slots, payload, slot_length=HOUR):
        """Link a recovery payload to its open request (or record it as unsolicited).

        Origin: Ashu
        """
        slots = sorted(slots, key=lambda slot: slot.start)
        monitor = None
        if recovery_type != DAILY_CONSUMPTION:
            monitor = (
                RecoveryMonitor.objects.filter(
                    site=self.site,
                    recovery_type=recovery_type,
                    status__in=OPEN_STATUSES,
                    **scope.monitor_filter(),
                )
                .order_by(*self.NEWEST_FIRST)
                .first()
            )
        if monitor is None:
            # Unsolicited (or a daily payload, which belongs to the hourly
            # request): keep it in the history as its own row.
            monitor = RecoveryMonitor(
                site=self.site,
                gateway_id=self.home_gateway_id,
                aisle_group=scope.aisle_group,
                leg_id=scope.leg_id,
                power_source=scope.power_source,
                recovery_type=recovery_type,
                missing_from=slots[0].start if slots else self.now,
                missing_to=(slots[-1].start + slot_length) if slots else self.now,
                expected_slots=len(slots),
                requested_at=self.now,
            )
        monitor.status = "response_received"
        monitor.response_received_at = self.now
        monitor.mqtt_response_payload = str(payload)[:MAX_PAYLOAD_CHARS]
        monitor.save()

        if recovery_type != DAILY_CONSUMPTION:
            self._write_status(
                scope,
                sync_status="recovery_received",
                is_sync_gone=True,
                recovery_requested=True,
                recovery_received=True,
                last_recovery_received_at=self.now,
                recovery_monitor=monitor,
            )
        return monitor

    def record_applied(self, monitor, scope, slots):
        """Rows are written: count, mark the catch-up hour, verify the gap.

        Origin: Ashu
        """
        slots = sorted(slots, key=lambda slot: slot.start)
        error_slots = sum(1 for slot in slots if slot.is_error)
        monitor.recovered_slots = len(slots) - error_slots
        monitor.error_slots = error_slots
        # Which hours had no data on the gateway (a later answer adds to the list).
        monitor.error_hours = sorted(
            set(monitor.error_hours or []) | {f"{slot.start:%Y-%m-%dT%H:%M:%S}" for slot in slots if slot.is_error}
        )
        monitor.applied_at = self.now
        monitor.catch_up_at = self._catch_up_slot(monitor, slots)
        monitor.status = "applied"

        if monitor.recovery_type == DAILY_CONSUMPTION:
            # History only: the hourly verification decides the aisle status.
            monitor.save()
            return monitor

        found = self._stored_slots(monitor, scope)
        if found >= monitor.expected_slots:
            monitor.status = "verified"
            monitor.verified_at = self.now
            monitor.is_active = False
            monitor.save()
            self._write_status(
                scope,
                sync_status="recovered",
                is_sync_gone=False,
                recovery_requested=False,
                recovery_received=True,
                last_recovery_applied_at=self.now,
                missing_slots=0,
                recovered_slots=monitor.recovered_slots,
                has_data_loss=error_slots > 0,
                last_error=None,
                recovery_monitor=monitor,
            )
        else:
            monitor.save()
            self._write_status(
                scope,
                sync_status="missing",
                is_sync_gone=True,
                recovery_requested=True,
                recovery_received=True,
                last_recovery_applied_at=self.now,
                missing_slots=monitor.expected_slots - found,
                recovered_slots=monitor.recovered_slots,
                has_data_loss=error_slots > 0,
                recovery_monitor=monitor,
            )
        return monitor

    @staticmethod
    def _catch_up_slot(monitor, slots):
        """First slot with data after the last ERROR404 slot (None if no errors).

        Origin: Ashu
        """
        last_error = max(
            (index for index, slot in enumerate(slots) if slot.is_error), default=None
        )
        if last_error is None:
            return None
        for slot in slots[last_error + 1 :]:
            if not slot.is_error:
                return slot.start
        # The outage ran to the end of the payload: live data resumes at the
        # hour that revealed the gap.
        return monitor.missing_to

    def _stored_slots(self, monitor, scope):
        """Hours already stored for a recovery request's range (run time or hourly readings), to see if
        recovery filled the gap.

        Origin: Ashu
        """
        if monitor.recovery_type == LOAD_RUNTIME:
            rows = SupplyLoadTimeShare.objects.filter(
                site=self.site, power_source=scope.power_source
            )
        else:
            rows = HourlySiteReading.objects.filter(
                associated_Site=self.site, leg_id=scope.leg_id
            )
        return (
            rows.filter(
                reading_from__gte=monitor.missing_from,
                reading_from__lt=monitor.missing_to,
            )
            .values("reading_from")
            .distinct()
            .count()
        )


# ------------------------------------------------------------ no-data hours
# ERROR404 hours are stored as 0 kWh rows, so they no longer look like a gap. A catch-up hour
# after them is still a catch-up (decided 2026-11-20): these helpers tell them from real 0 kWh
# hours (lights off at night), which must stay as they are.
def no_data_monitors(site_ids, since, until=None):
    """``{(site_id, leg_id): [(catch_up_at, error_slots, error_hours)]}``: hourly recoveries whose
    gateway had no data for some hours, with their catch-up hour in [since, until).

    Origin: Ashu
    """
    rows = RecoveryMonitor.objects.filter(
        site_id__in=list(site_ids), recovery_type=HOURLY_CONSUMPTION, error_slots__gt=0,
        catch_up_at__gte=since, leg_id__isnull=False,
    )
    if until is not None:
        rows = rows.filter(catch_up_at__lt=until)
    found = {}
    for site_id, leg_id, catch_up_at, error_slots, error_hours in rows.values_list(
        "site_id", "leg_id", "catch_up_at", "error_slots", "error_hours"
    ):
        found.setdefault((site_id, str(leg_id)), []).append((catch_up_at, error_slots, error_hours or []))
    return found


def no_data_hours(monitors, values):
    """Hours of one aisle stored as 0 because the gateway had no data.

    ``monitors``: that aisle's list from ``no_data_monitors``; ``values``: ``{hour start: kWh}``.
    Uses the ERROR404 hours kept on the request; for older requests (before 2026-11-20) the run
    of 0 kWh hours right before the catch-up hour, at most ``error_slots`` long. An hour whose
    value is no longer 0 (real data came later) is not counted.

    Origin: Ashu
    """
    hours = set()
    for catch_up_at, error_slots, error_hours in monitors:
        if error_hours:
            for text in error_hours:
                hour = datetime.fromisoformat(text)
                if values.get(hour) == 0:
                    hours.add(hour)
            continue
        step = catch_up_at - HOUR
        while error_slots > 0 and values.get(step) == 0:
            hours.add(step)
            step -= HOUR
            error_slots -= 1
    return hours
