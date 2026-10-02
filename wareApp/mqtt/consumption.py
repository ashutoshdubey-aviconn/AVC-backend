import logging
from datetime import datetime, timedelta

from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    DailySiteReading,
    HourlySiteReading,
    SensorAisleUnitConsumption,
    SiteBaseline,
)

logger = logging.getLogger(__name__)


def _parse_consumption_message(message):
    data = message.split(",")
    message_time = data[3].split(":")[1].split(" ")
    return {
        "consumption_time": float(data[0].split(":")[1]),
        "new_unit_consumption": float(data[1].split(":")[1]),
        "observed_date": datetime.strptime(message_time[0], "%Y-%m-%d"),
        "observed_hour": int(message_time[1]),
        "current_hour_consumption": float(data[5].split(":")[1]),
        "aisle_group_id": int(data[6].split(":")[1]),
        "previous_hour_consumption": float(data[8].split(":")[1]),
    }


def _hourly_baseline(location_id, aisle_group_id):
    baseline = SiteBaseline.objects.filter(
        associated_site_id=int(location_id), leg_id=str(aisle_group_id)
    ).last()
    return baseline.baseline_value / baseline.working_hours, baseline.baseline_value


def _consumption_alarms(site, leg_id, current_consumption):
    current_date = datetime.now()
    daily_readings = DailySiteReading.objects.filter(
        associated_Site=site.id,
        leg_id=leg_id,
        reading_for__gte=(current_date - timedelta(days=7)).date(),
    )
    average_consumption = sum(
        reading.unit_consumption for reading in daily_readings
    ) / 7
    maximum = round(
        average_consumption
        + (average_consumption * site.max_threshold_value) / 100,
        2,
    )
    minimum = round(
        average_consumption
        - (average_consumption * site.min_threshold_value) / 100,
        2,
    )
    if current_consumption > maximum:
        AlarmNotifications.objects.create(
            created_by=None,
            user_level=2,
            site_id=site.id,
            object_type=0,
            Alarm_type=7,
            Alarm_priority=1,
            created_time=current_date,
        )
    elif current_consumption < minimum:
        AlarmNotifications.objects.create(
            created_by=None,
            user_level=2,
            site_id=site.id,
            object_type=0,
            Alarm_type=8,
            Alarm_priority=1,
            created_time=current_date,
        )


def _publish_consumption_recovery(
    publish_recovery, location_id, gateway_id, aisle_group_id, last_hourly_entry
):
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


def handle_consumption_message(site, location_id, gateway_id, message, publish_recovery):
    """Persist a gateway consumption packet outside the Paho callback."""
    try:
        values = _parse_consumption_message(message)
        observed_at = values["observed_date"].replace(
            hour=values["observed_hour"], minute=0, second=0, microsecond=0
        )
        hour_end = observed_at.replace(minute=59, second=59)
        aisle_group_id = values["aisle_group_id"]
        aisle_group = AisleGroup.objects.filter(
            site=site, attached_leg_id=str(aisle_group_id)
        ).first()
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

        hourly_entries = HourlySiteReading.objects.filter(
            associated_Site=site, leg_id=aisle_group_id
        )
        current_hour_entries = hourly_entries.filter(
            reading_from__gte=observed_at, reading_from__lte=hour_end
        )
        daily_entries = DailySiteReading.objects.filter(
            associated_Site=site, leg_id=aisle_group_id, reading_for=observed_at.date()
        )
        daily_record = daily_entries.first()

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
                if (
                    previous_record.unit_consumption
                    != values["previous_hour_consumption"]
                ):
                    previous_entries.update(
                        unit_consumption=values["previous_hour_consumption"]
                    )
                    previous_record.unit_consumption = values["previous_hour_consumption"]

                hourly_baseline = 0.0
                if aisle_group.is_active:
                    hourly_baseline, _ = _hourly_baseline(location_id, aisle_group_id)
                    previous_entries.update(
                        energy_saved=(
                            hourly_baseline - previous_record.unit_consumption
                        )
                    )

                if daily_record:
                    hourly_readings = HourlySiteReading.objects.filter(
                        associated_Site=site,
                        aisle_group=aisle_group,
                        reading_from__date=observed_at.date(),
                        reading_to__date=observed_at.date(),
                    )
                    total = sum(reading.unit_consumption for reading in hourly_readings)
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
            elif hourly_entries.exists():
                _publish_consumption_recovery(
                    publish_recovery,
                    location_id,
                    gateway_id,
                    aisle_group_id,
                    hourly_entries.last(),
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
                return

        daily_baseline = 0.0
        if aisle_group.is_active:
            _, daily_baseline = _hourly_baseline(location_id, aisle_group_id)
        if daily_record:
            new_consumption = (
                daily_record.unit_consumption + values["new_unit_consumption"]
            )
            daily_entries.update(
                unit_consumption=new_consumption,
                energy_saved=daily_baseline - new_consumption,
                daily_baseline_value=daily_baseline,
            )
        else:
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
                _consumption_alarms(site, aisle_group_id, yesterday.unit_consumption)
    except Exception:
        logger.exception(
            "Queue1 consumption processing failed for site %s from gateway %s",
            location_id,
            gateway_id,
        )