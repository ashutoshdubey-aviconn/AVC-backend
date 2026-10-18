import logging
import re
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    DailySiteReading,
    HourlySiteReading,
    SensorAisleUnitConsumption,
    SiteBaseline,
)
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.sync_status import mark_recovery_requested, mark_sync_healthy

logger = logging.getLogger(__name__)

METER_READING_ISSUE_COOLDOWN_SECONDS = 30 * 60
METER_READING_ISSUE_PATTERN = re.compile(
    r"New meter reading for energy of aisle group id\s+(?P<meter_id>\d+)\s+"
    r"is smaller than previous meter reading",
    re.IGNORECASE,
)


def _parse_consumption_message(message):
    fields = {}
    for field in str(message).split(","):
        key, separator, value = field.partition(":")
        if not separator:
            raise ValueError(f"Invalid consumption field: {field!r}")
        fields[key.strip().lower().replace("_", "").replace("-", "")] = value.strip()

    def value_for(*keys):
        for key in keys:
            if key in fields:
                return fields[key]
        raise ValueError(f"Missing consumption field: {keys[0]}")

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
    if not match:
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

    AlarmNotifications.objects.create(
        created_by=None,
        user_level=2,
        site_id=site.id,
        object_type=4,
        object_id=int(meter_id),
        aisle_group=aisle_group,
        Alarm_type=10,
        Alarm_priority=1,
        created_time=occurred_at,
        to_do=f"Gateway {gateway_id}: lower meter reading reported.",
    )

    logger.warning(
        "Meter reading issue stored: site=%s home_gateway_id=%s meter_id=%s aisle_group_name=%s occurred_at=%s",
        location_id,
        gateway_id,
        meter_id,
        aisle_group_name,
        occurred_at,
    )


def _hourly_baseline(location_id, aisle_group_id):
    baseline = (
        SiteBaseline.objects.filter(
            associated_site_id=int(location_id), leg_id=str(aisle_group_id)
        )
        .order_by("-baseline_to", "-id")
        .values_list("baseline_value", "working_hours")
        .first()
    )
    if baseline is None:
        logger.warning(
            "No baseline configured for site %s, leg %s", location_id, aisle_group_id
        )
        return 0.0, 0.0

    baseline_value, working_hours = baseline
    if not working_hours:
        logger.warning(
            "No working hours configured for baseline at site %s, leg %s",
            location_id,
            aisle_group_id,
        )
        return 0.0, baseline_value
    return baseline_value / working_hours, baseline_value


def _record_daily_consumption_alarm(
    site, aisle_group, daily_reading, alarm_type, threshold, description
):
    if AlarmNotifications.objects.filter(
        site_id=site.id,
        aisle_group=aisle_group,
        Alarm_type=alarm_type,
        created_time__date=daily_reading.reading_for,
        is_active=True,
    ).exists():
        return

    meter_id = str(aisle_group.attached_leg_id or "")
    object_id = int(meter_id) if meter_id.isdigit() else None
    AlarmNotifications.objects.create(
        created_by=None,
        user_level=2,
        site_id=site.id,
        object_type=4,
        object_id=object_id,
        aisle_group=aisle_group,
        Alarm_type=alarm_type,
        Alarm_priority=1,
        created_time=datetime.combine(daily_reading.reading_for, datetime.min.time()),
        to_do=(
            f"{description}: consumption={daily_reading.unit_consumption:.2f}, "
            f"threshold={threshold:.2f}."
        ),
    )


def _consumption_alarms(site, aisle_group, daily_reading):
    current_consumption = daily_reading.unit_consumption
    daily_baseline = daily_reading.daily_baseline_value
    high_threshold = getattr(site, "high_consumption_units", None)
    bypass_threshold = getattr(site, "bypass_consumption_units", None)

    if high_threshold is None:
        baseline_percent = getattr(site, "high_consumption_baseline_percent", None)
        if baseline_percent is not None and daily_baseline:
            high_threshold = daily_baseline * baseline_percent / 100

    if bypass_threshold is not None and current_consumption >= bypass_threshold:
        _record_daily_consumption_alarm(
            site,
            aisle_group,
            daily_reading,
            alarm_type=11,
            threshold=bypass_threshold,
            description="Bypassed",
        )
        return

    if high_threshold is not None and current_consumption >= high_threshold:
        _record_daily_consumption_alarm(
            site,
            aisle_group,
            daily_reading,
            alarm_type=7,
            threshold=high_threshold,
            description="High consumption",
        )
        return

    if site.min_threshold_value is None:
        logger.warning(
            "Skipping legacy low-consumption alarm for site %s without a threshold",
            site.id,
        )
        return

    current_date = datetime.combine(daily_reading.reading_for, datetime.min.time())
    daily_readings = DailySiteReading.objects.filter(
        associated_Site=site.id,
        leg_id=aisle_group.attached_leg_id,
        reading_for__gte=(current_date - timedelta(days=7)).date(),
    )
    average_consumption = (
        daily_readings.aggregate(total=Sum("unit_consumption"))["total"] or 0
    ) / 7
    minimum = round(
        average_consumption - (average_consumption * site.min_threshold_value) / 100,
        2,
    )
    if current_consumption < minimum:
        AlarmNotifications.objects.create(
            created_by=None,
            user_level=2,
            site_id=site.id,
            object_type=0,
            aisle_group=aisle_group,
            Alarm_type=8,
            Alarm_priority=1,
            created_time=current_date,
        )


def _publish_consumption_recovery(
    publish_recovery, location_id, gateway_id, aisle_group_id, last_hourly_entry
):
    if not last_hourly_entry.reading_to:
        logger.warning(
            "Skipping consumption recovery with incomplete prior reading: site=%s homegateway_id=%s aisle_group=%s reading_id=%s",
            location_id,
            gateway_id,
            aisle_group_id,
            last_hourly_entry.id,
        )
        return False

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
    publish_recovery(topic, message)
    return True


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
            return

        values = _cap_warehouse_saving_values(
            site, _parse_consumption_message(message)
        )
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
        daily_record = None

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
                daily_record = daily_entries.first()
                if (
                    previous_record.unit_consumption
                    != values["previous_hour_consumption"]
                ):
                    previous_entries.update(
                        unit_consumption=values["previous_hour_consumption"]
                    )
                    previous_record.unit_consumption = values[
                        "previous_hour_consumption"
                    ]

                hourly_baseline = 0.0
                if aisle_group.is_active:
                    hourly_baseline, _ = _hourly_baseline(location_id, aisle_group_id)
                    previous_entries.update(
                        energy_saved=(
                            hourly_baseline - previous_record.unit_consumption
                        )
                    )

                if daily_record:
                    day_start = observed_at.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    hourly_readings = HourlySiteReading.objects.filter(
                        associated_Site=site,
                        aisle_group=aisle_group,
                        reading_from__gte=day_start,
                        reading_from__lt=day_start + timedelta(days=1),
                    )
                    total = (
                        hourly_readings.aggregate(total=Sum("unit_consumption"))[
                            "total"
                        ]
                        or 0
                    )
                    if total != daily_record.unit_consumption:
                        daily_record.unit_consumption = total
                        daily_record.save()

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
            elif hourly_entries.exists():
                last_hourly_entry = hourly_entries.order_by(
                    "-reading_to", "-id"
                ).first()
                recovery_requested = _publish_consumption_recovery(
                    publish_recovery,
                    location_id,
                    gateway_id,
                    aisle_group_id,
                    last_hourly_entry,
                )
                if recovery_requested:
                    mark_recovery_requested(
                        site,
                        home_gateway_id,
                        aisle_group,
                        last_hourly_entry.reading_to,
                        observed_at,
                    )
                    logger.warning(
                        "Queue1 consumption recovery requested: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s observed_at=%s",
                        location_id,
                        home_gateway_id,
                        aisle_group_id,
                        aisle_group.aisleGroupName,
                        observed_at,
                    )
                return
            else:
                hourly_baseline = daily_baseline = 0.0
                if aisle_group.is_active:
                    hourly_baseline, daily_baseline = _hourly_baseline(
                        location_id, aisle_group_id
                    )
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
                return

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

        daily_baseline = 0.0
        if aisle_group.is_active:
            _, daily_baseline = _hourly_baseline(location_id, aisle_group_id)
        if daily_record:
            daily_entries.update(
                unit_consumption=F("unit_consumption") + values["new_unit_consumption"],
                energy_saved=daily_baseline
                - (F("unit_consumption") + values["new_unit_consumption"]),
                daily_baseline_value=daily_baseline,
            )
        else:
            if not daily_entries.update(
                unit_consumption=F("unit_consumption") + values["new_unit_consumption"],
                energy_saved=daily_baseline
                - (F("unit_consumption") + values["new_unit_consumption"]),
                daily_baseline_value=daily_baseline,
            ):
                DailySiteReading.objects.create(
                    associated_Site=site,
                    aisle_group=aisle_group,
                    leg_id=aisle_group_id,
                    unit_consumption=values["new_unit_consumption"],
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
    except Exception:
        logger.exception(
            "Queue1 consumption processing failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
