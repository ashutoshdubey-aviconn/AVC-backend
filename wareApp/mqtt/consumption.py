import logging
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, FloatField, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from wareApp.mqtt.services import alarm_policy
from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    DailySiteReading,
    HourlySiteReading,
    SensorAisleUnitConsumption,
)
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.log_format import missing_hours
from wareApp.mqtt.payloads import KeyValuePayload
from wareApp.mqtt.services.failures import TRANSIENT_DB_ERRORS, record_dead_letter
from wareApp.mqtt.services.notifications import notify
from wareApp.mqtt.services.baseline import BaselineMemo
from wareApp.mqtt.services.consumption_alarms import evaluate_daily_alarms
from wareApp.mqtt.services.cooldown import (
    recovery_request_allowed,
    release_recovery_request,
)
from wareApp.mqtt.services.recovery_status import (
    HOURLY_CONSUMPTION,
    RecoveryScope,
    RecoveryStatusService,
)
from wareApp.mqtt.sync_status import mark_sync_healthy
from wareApp.sendmail import send_alarm_email

logger = logging.getLogger(__name__)

METER_READING_ISSUE_COOLDOWN_SECONDS = 30 * 60
METER_READING_ISSUE_PATTERN = re.compile(
    r"New meter reading for energy of aisle group id\s+(?P<meter_id>\d+)\s+"
    r"is smaller than previous meter reading",
    re.IGNORECASE,
)


def _parse_consumption_message(message):
    value_for = KeyValuePayload.parse(message, "consumption").get

    message_time = value_for("time", "messagetime").split()
    if len(message_time) != 2:
        raise ValueError("Invalid consumption timestamp")

    try:
        observed_date = datetime.strptime(message_time[0], "%Y-%m-%d")
        observed_hour = int(message_time[1])
    except ValueError:
        try:
            observed_at = datetime.fromisoformat(" ".join(message_time))
        except ValueError as error:
            raise ValueError("Invalid consumption timestamp") from error
        observed_date = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
        observed_hour = observed_at.hour

    return {
        "consumption_time": float(value_for("consumptiontime", "consumptiontimeinsec")),
        "new_unit_consumption": float(value_for("consumption", "unitconsumption")),
        "observed_date": observed_date,
        "observed_hour": observed_hour,
        "current_hour_consumption": float(value_for("currenthourtotalconsumption")),
        "aisle_group_id": int(value_for("aislegroup", "aislegrpid")),
        "previous_hour_consumption": float(value_for("previoushourtotalconsumption")),
    }


WAREHOUSE_SAVING_SITE_TYPE = 2
WAREHOUSE_SAVING_MAX_UNITS = 10000


def _cap_warehouse_saving_values(site, values):
    """Apply the legacy guard against meter glitches on energy-saving sites.

    The legacy root tasks.py replaced any consumption above 10000 units with 0
    for ``site_type == 2`` sites; the modular handler keeps that behaviour.
    """
    if getattr(site, "site_type", None) != WAREHOUSE_SAVING_SITE_TYPE:
        return values
    for key in (
        "new_unit_consumption",
        "current_hour_consumption",
        "previous_hour_consumption",
    ):
        if values[key] > WAREHOUSE_SAVING_MAX_UNITS:
            logger.warning(
                "Consumption value above %s replaced with 0: site=%s field=%s value=%s",
                WAREHOUSE_SAVING_MAX_UNITS,
                getattr(site, "id", None),
                key,
                values[key],
            )
            values[key] = 0.0
    return values


def _notify_meter_reading_issue(site, location_id, gateway_id, message):
    match = METER_READING_ISSUE_PATTERN.search(str(message))
    if not match or alarm_policy.is_off(site.id, 10):
        return

    meter_id = match.group("meter_id")
    aisle_group = AisleGroup.objects.filter(site=site, attached_leg_id=meter_id).first()
    aisle_group_name = aisle_group.aisleGroupName if aisle_group else "Unknown"
    occurred_at = timezone.now()
    cache_key = f"meter-reading-issue-storage:{location_id}:{gateway_id}:{meter_id}"
    if not cache.add(cache_key, True, timeout=METER_READING_ISSUE_COOLDOWN_SECONDS):
        logger.info(
            "Meter reading issue storage throttled: site=%s home_gateway_id=%s meter_id=%s",
            location_id,
            gateway_id,
            meter_id,
        )
        return

    day_start = datetime.combine(occurred_at.date(), datetime.min.time())
    # The same issue already raised today: count it on that alarm instead of
    # storing (and e-mailing) another row every cooldown window.
    repeated = AlarmNotifications.objects.filter(
        site_id=site,
        object_id=int(meter_id),
        Alarm_type=10,
        is_active=True,
        created_time__gte=day_start,
    ).update(last_seen=occurred_at, occurrences=F("occurrences") + 1)
    if repeated:
        logger.warning(
            "Meter reading issue repeated (active alarm updated): site=%s home_gateway_id=%s meter_id=%s aisle_group_name=%s occurred_at=%s",
            location_id,
            gateway_id,
            meter_id,
            aisle_group_name,
            occurred_at,
        )
        return

    AlarmNotifications.objects.create(
        created_by=None,
        user_level=2,
        site_id=site,
        object_type=4,
        object_id=int(meter_id),
        aisle_group=aisle_group,
        Alarm_type=10,
        Alarm_priority=1,
        created_time=occurred_at,
        last_seen=occurred_at,
        to_do=f"Gateway {gateway_id}: lower meter reading reported.",
    )
    notify(
        send_alarm_email,
        "Meter Reading Issue",
        site.id,
        [
            ["Gateway", gateway_id, False],
            ["Leg / meter", meter_id, False],
            ["Aisle group", aisle_group_name, False],
            ["Issue", "New meter reading is smaller than the previous one", True],
        ],
        10,  # Meter Reading Issue
    )

    logger.warning(
        "Meter reading issue stored: site=%s home_gateway_id=%s meter_id=%s aisle_group_name=%s occurred_at=%s",
        location_id,
        gateway_id,
        meter_id,
        aisle_group_name,
        occurred_at,
    )


def _consumption_alarms(site, aisle_group, daily_reading):
    """Day-end alarms (see services/consumption_alarms.py)."""
    return evaluate_daily_alarms(site, aisle_group, daily_reading)


def stale_history(location_id, home_gateway_id, aisle_group, last_hourly_entry, observed_at):
    """True when the aisle has no hourly reading for over MQTT_RECOVERY_STALE_DAYS.

    Such an aisle is inactive for MQTT: its daily totals come from the gateway
    sync, so the packet is dropped without a recovery request (the gateway no
    longer holds that history) and nothing is stored that would overwrite the
    synced total. Logged once per aisle per day.
    """
    stale_days = getattr(settings, "MQTT_RECOVERY_STALE_DAYS", 30)
    if not stale_days or observed_at - last_hourly_entry.reading_from <= timedelta(days=stale_days):
        return False
    log_key = f"mqtt:stale-aisle:{location_id}:{aisle_group.id}:{observed_at:%Y-%m-%d}"
    if cache.add(log_key, True, timeout=26 * 60 * 60):
        logger.warning(
            "Queue1 consumption skipped, aisle inactive (no hourly data for over %s days, no recovery requested): site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s last_stored_hour=%s observed_at=%s",
            stale_days,
            location_id,
            home_gateway_id,
            aisle_group.id,
            aisle_group.aisleGroupName,
            last_hourly_entry.reading_from,
            observed_at,
        )
    return True


def _consumption_recovery_request(
    location_id, gateway_id, aisle_group_id, last_hourly_entry
):
    """Build the gateway sync command for a consumption gap, or None."""
    if not last_hourly_entry.reading_to:
        logger.warning(
            "Skipping consumption recovery with incomplete prior reading: site=%s homegateway_id=%s aisle_group=%s reading_id=%s",
            location_id,
            gateway_id,
            aisle_group_id,
            last_hourly_entry.id,
        )
        return None

    topic = (
        f"/Acclivate/iOmniControl/{location_id}/{gateway_id}/in/sync/"
        "consumption/state"
    )
    elapsed = datetime.now() - last_hourly_entry.reading_to
    message = (
        f"Missed_consumption_time_in_secs :{elapsed.total_seconds()},"
        f"Aisle_grp :{aisle_group_id},Last_Synced_hour :"
        f"{last_hourly_entry.reading_to.strftime('%Y-%m-%d %H:%M:%S.%f')}"
    )
    return topic, message


class _BaselineMemo:
    """Baseline of the packet's aisle and day (see services/baseline.py)."""

    def __init__(self, site, aisle_group, day, home_gateway_id=None):
        self._memo = BaselineMemo(site, aisle_group)
        self._day = day
        self._home_gateway_id = home_gateway_id

    def _values(self):
        values = self._memo.for_day(self._day)
        if self._memo.missing_days:
            self._warn_missing()
        return values

    def _warn_missing(self):
        site, aisle = self._memo.site, self._memo.aisle_group
        # Once per aisle per hour instead of on every packet.
        if cache.add(
            f"baseline-missing-log:{site.id}:{aisle.attached_leg_id}", 1, 3600
        ):
            logger.warning(
                "Queue1 consumption baseline missing (saving not calculated): site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s day=%s",
                site.id,
                self._home_gateway_id,
                aisle.attached_leg_id,
                getattr(aisle, "aisleGroupName", ""),
                self._day,
            )

    @property
    def hourly(self):
        return self._values()[0]

    @property
    def daily(self):
        return self._values()[1]


def _daily_total_from_hourly(site, leg_id, day):
    """SQL expression: the day's total = sum of its hourly readings (0 if none).

    The daily row always equals what the hourly rows say. (Previously each
    packet added its new units to the day and the day was re-summed only at
    the hour change, so the two drifted apart whenever a packet's units did
    not match the hour total.)
    """
    day_start = datetime.combine(day, datetime.min.time())
    hourly_total = (
        HourlySiteReading.objects.filter(
            associated_Site=site,
            leg_id=leg_id,
            reading_from__gte=day_start,
            reading_from__lt=day_start + timedelta(days=1),
        )
        .order_by()
        .values("leg_id")
        .annotate(total=Sum("unit_consumption"))
        .values("total")[:1]
    )
    return Coalesce(Subquery(hourly_total, output_field=FloatField()), Value(0.0))


def _daily_updates(site, leg_id, day, daily_baseline):
    total = _daily_total_from_hourly(site, leg_id, day)
    return {
        "unit_consumption": total,
        "energy_saved": Value(float(daily_baseline)) - total,
        "daily_baseline_value": daily_baseline,
    }


@transaction.atomic
def handle_consumption_message(
    site, location_id, gateway_id, message, publish_recovery
):
    """Persist a gateway consumption packet outside the Paho callback."""
    home_gateway_id = home_gateway_id_for(location_id, gateway_id)
    try:
        if str(message).strip().startswith("ERROR!!!"):
            logger.warning(
                "Gateway consumption diagnostic: site=%s home_gateway_id=%s message=%s",
                location_id,
                home_gateway_id,
                message,
            )
            _notify_meter_reading_issue(site, location_id, home_gateway_id, message)
            return "skipped: gateway diagnostic (meter reading issue stored)"

        values = _cap_warehouse_saving_values(site, _parse_consumption_message(message))
        observed_at = values["observed_date"].replace(
            hour=values["observed_hour"], minute=0, second=0, microsecond=0
        )
        hour_end = observed_at.replace(minute=59, second=59)
        aisle_group_id = values["aisle_group_id"]
        aisle_group = (
            AisleGroup.objects.select_for_update()
            .filter(site=site, attached_leg_id=str(aisle_group_id))
            .first()
        )
        if not aisle_group:
            raise ValueError(f"Missing aisle group for leg {aisle_group_id}")

        if aisle_group.on_sensor_power:
            SensorAisleUnitConsumption.objects.create(
                associated_Site=site,
                aisle_group=aisle_group,
                leg_id=aisle_group_id,
                unit_consumption=values["new_unit_consumption"],
                reading_for=observed_at,
            )
            logger.info(
                "Queue1 consumption sensor reading created: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s observed_at=%s",
                location_id,
                home_gateway_id,
                aisle_group_id,
                aisle_group.aisleGroupName,
                values["new_unit_consumption"],
                observed_at,
            )

        hourly_entries = HourlySiteReading.objects.filter(
            associated_Site=site, leg_id=aisle_group_id
        )
        current_hour_entries = hourly_entries.filter(
            reading_from__gte=observed_at, reading_from__lte=hour_end
        )
        daily_entries = DailySiteReading.objects.filter(
            associated_Site=site, leg_id=aisle_group_id, reading_for=observed_at.date()
        )
        baselines = _BaselineMemo(
            site, aisle_group, observed_at.date(), home_gateway_id
        )

        if not current_hour_entries.update(
            unit_consumption=values["current_hour_consumption"]
        ):
            previous_start = observed_at - timedelta(hours=1)
            previous_end = hour_end - timedelta(hours=1)
            previous_entries = hourly_entries.filter(
                reading_from__gte=previous_start, reading_from__lte=previous_end
            )
            previous_record = previous_entries.first()
            if previous_record:
                # Sync the previous hour with the gateway total and store its
                # saving in one UPDATE (previously up to two).
                previous_updates = {}
                if (
                    previous_record.unit_consumption
                    != values["previous_hour_consumption"]
                ):
                    previous_updates["unit_consumption"] = values[
                        "previous_hour_consumption"
                    ]
                    previous_record.unit_consumption = values[
                        "previous_hour_consumption"
                    ]

                hourly_baseline = baselines.hourly
                if aisle_group.is_active:
                    previous_updates["energy_saved"] = (
                        hourly_baseline - previous_record.unit_consumption
                    )
                if previous_updates:
                    previous_entries.update(**previous_updates)

                HourlySiteReading.objects.create(
                    associated_Site=site,
                    aisle_group=aisle_group,
                    leg_id=aisle_group_id,
                    unit_consumption=values["new_unit_consumption"],
                    hourly_baseline_value=hourly_baseline,
                    reading_from=observed_at,
                    reading_to=hour_end,
                    is_visible=True,
                )
                logger.info(
                    "Queue1 consumption hourly reading created: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s hour_total=%s observed_at=%s",
                    location_id,
                    home_gateway_id,
                    aisle_group_id,
                    aisle_group.aisleGroupName,
                    values["new_unit_consumption"],
                    values["current_hour_consumption"],
                    observed_at,
                )
            else:
                if not recovery_request_allowed(location_id, "aisle", aisle_group_id):
                    # This gap was already requested inside the cooldown window:
                    # keep dropping the packet (agreed behaviour) without another
                    # query, publish or sync-status write.
                    logger.info(
                        "Queue1 consumption skipped, gap recovery already requested (cooldown): site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s observed_at=%s",
                        location_id,
                        home_gateway_id,
                        aisle_group_id,
                        aisle_group.aisleGroupName,
                        observed_at,
                    )
                    return (
                        f"skipped: leg {aisle_group_id} has a gap, recovery already "
                        "requested (cooldown)"
                    )
                # One indexed query (backward scan, LIMIT 1) replaces the former
                # exists() + order_by("-reading_to") pair.
                last_hourly_entry = hourly_entries.order_by(
                    "-reading_from", "-id"
                ).first()
                if last_hourly_entry is not None:
                    if stale_history(
                        location_id, home_gateway_id, aisle_group, last_hourly_entry, observed_at
                    ):
                        return f"skipped: leg {aisle_group_id} inactive, no recovery requested"
                    request = _consumption_recovery_request(
                        location_id, gateway_id, aisle_group_id, last_hourly_entry
                    )
                    if request is not None:
                        topic, request_message = request
                        decision = RecoveryStatusService(
                            site, home_gateway_id
                        ).request_recovery(
                            RecoveryScope.aisle(aisle_group),
                            HOURLY_CONSUMPTION,
                            last_hourly_entry.reading_from,
                            observed_at,
                            topic,
                            request_message,
                        )
                        gap = missing_hours(
                            decision.monitor.missing_from, decision.monitor.missing_to
                        )
                        if decision.publish:
                            publish_recovery(topic, request_message)
                            logger.warning(
                                "Queue1 consumption recovery requested: site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s missing=%s last_stored_hour=%s observed_at=%s attempt=%s",
                                location_id,
                                home_gateway_id,
                                aisle_group_id,
                                aisle_group.aisleGroupName,
                                gap,
                                last_hourly_entry.reading_from,
                                observed_at,
                                decision.monitor.attempt,
                            )
                            return (
                                f"skipped: leg {aisle_group_id} gap {gap}, recovery "
                                f"requested (attempt {decision.monitor.attempt})"
                            )
                        logger.warning(
                            "Queue1 consumption skipped, recovery failed for gap: site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s missing=%s attempts=%s",
                            location_id,
                            home_gateway_id,
                            aisle_group_id,
                            aisle_group.aisleGroupName,
                            gap,
                            decision.monitor.attempt,
                        )
                        return (
                            f"skipped: leg {aisle_group_id} gap {gap}, recovery failed "
                            f"after {decision.monitor.attempt} attempts"
                        )
                    return (
                        f"skipped: leg {aisle_group_id} gap, no recovery request "
                        "(previous reading incomplete)"
                    )

                # First ever reading for this aisle: no gap, so give back the
                # cooldown slot claimed above.
                release_recovery_request(location_id, "aisle", aisle_group_id)
                hourly_baseline = baselines.hourly
                daily_baseline = baselines.daily
                HourlySiteReading.objects.create(
                    associated_Site=site,
                    aisle_group=aisle_group,
                    leg_id=aisle_group_id,
                    unit_consumption=values["new_unit_consumption"],
                    hourly_baseline_value=hourly_baseline,
                    reading_from=observed_at,
                    reading_to=hour_end,
                    is_visible=True,
                )
                DailySiteReading.objects.create(
                    associated_Site=site,
                    aisle_group=aisle_group,
                    leg_id=aisle_group_id,
                    unit_consumption=values["new_unit_consumption"],
                    daily_baseline_value=daily_baseline,
                    reading_for=observed_at.date(),
                    is_visible=True,
                )
                logger.info(
                    "Queue1 consumption hourly and daily readings created: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s hour_total=%s observed_at=%s",
                    location_id,
                    home_gateway_id,
                    aisle_group_id,
                    aisle_group.aisleGroupName,
                    values["new_unit_consumption"],
                    values["current_hour_consumption"],
                    observed_at,
                )
                mark_sync_healthy(site, home_gateway_id, aisle_group, observed_at)
                return (
                    f"stored: leg {aisle_group_id} first hourly+daily reading "
                    f"{observed_at:%Y-%m-%d %H:00}"
                )

        else:
            logger.info(
                "Queue1 consumption hourly reading updated: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s hour_total=%s observed_at=%s",
                location_id,
                home_gateway_id,
                aisle_group_id,
                aisle_group.aisleGroupName,
                values["current_hour_consumption"],
                observed_at,
            )

        # The day's total is the sum of its hourly rows (one UPDATE).
        daily_baseline = baselines.daily
        if not daily_entries.update(
            **_daily_updates(site, aisle_group_id, observed_at.date(), daily_baseline)
        ):
            # First packet of the day: create the row with the hourly sum.
            day_start = datetime.combine(observed_at.date(), datetime.min.time())
            total = (
                HourlySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id=aisle_group_id,
                    reading_from__gte=day_start,
                    reading_from__lt=day_start + timedelta(days=1),
                ).aggregate(total=Sum("unit_consumption"))["total"]
                or 0.0
            )
            DailySiteReading.objects.create(
                associated_Site=site,
                aisle_group=aisle_group,
                leg_id=aisle_group_id,
                unit_consumption=total,
                energy_saved=daily_baseline - total,
                daily_baseline_value=daily_baseline,
                reading_for=observed_at.date(),
                is_visible=True,
            )
            yesterday = DailySiteReading.objects.filter(
                associated_Site=site,
                leg_id=aisle_group_id,
                reading_for=observed_at.date() - timedelta(days=1),
            ).first()
            if yesterday:
                _consumption_alarms(site, aisle_group, yesterday)

        logger.info(
            "Queue1 consumption daily reading updated: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s observed_date=%s",
            location_id,
            home_gateway_id,
            aisle_group_id,
            aisle_group.aisleGroupName,
            values["new_unit_consumption"],
            observed_at.date(),
        )
        mark_sync_healthy(site, home_gateway_id, aisle_group, observed_at)
        return (
            f"stored: leg {aisle_group_id} hour {observed_at:%Y-%m-%d %H:00} "
            f"total={values['current_hour_consumption']}"
        )
    except TRANSIENT_DB_ERRORS:
        raise
    except Exception as error:
        logger.exception(
            "Queue1 consumption processing failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
        record_dead_letter("consumption", location_id, gateway_id, message, error)
        return f"failed: {type(error).__name__}: {str(error)[:80]} (dead letter)"
