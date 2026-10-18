import logging
import re
from datetime import datetime

from wareApp.models import AisleGroup, HourlySiteReading
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.sync_status import mark_recovered, mark_recovery_received

logger = logging.getLogger(__name__)


def _parse_hourly_recovery_message(message):
    match = re.search(
        r"Aisle_group_id : (.*); Recovery_Hours : (.*); Unit_consumptions : (.*);"
        r" GW_total_cumulative : (.*)",
        message,
    )
    if not match:
        raise ValueError("Invalid hourlyConsumption recovery payload")

    aisle_group_id, recovery_hours, unit_consumptions, _ = match.groups()
    return (
        aisle_group_id,
        [value for value in recovery_hours.split(",") if value],
        [value for value in unit_consumptions.split(",") if value],
    )


def handle_hourly_consumption_recovery_message(site, location_id, gateway_id, message):
    """Persist recovered hourly consumption readings for one aisle group."""
    home_gateway_id = home_gateway_id_for(location_id, gateway_id)
    try:
        aisle_group_id, recovery_hours, recovery_values = (
            _parse_hourly_recovery_message(message)
        )
        aisle_group = AisleGroup.objects.filter(
            site=site, attached_leg_id=aisle_group_id
        ).first()
        if not aisle_group:
            raise ValueError(f"Missing aisle group for leg {aisle_group_id}")

        mark_recovery_received(site, home_gateway_id, aisle_group)
        for recovery_hour, recovery_value in zip(recovery_hours, recovery_values):
            observed_at = datetime.strptime(recovery_hour, "%Y-%m-%d %H:%M:%S.%f")
            hour_start = observed_at.replace(minute=0, second=0, microsecond=0)
            hour_end = observed_at.replace(minute=59, second=59, microsecond=0)
            consumption = 0.0 if recovery_value == "ERROR404" else float(recovery_value)
            hourly_baseline = 0.0
            saving = 0.0

            hourly_entries = HourlySiteReading.objects.filter(
                associated_Site=site,
                leg_id=aisle_group_id,
                reading_from=hour_start,
                reading_to=hour_end,
            )
            if hourly_entries.update(
                unit_consumption=consumption,
                hourly_baseline_value=hourly_baseline,
                energy_saved=saving,
            ):
                logger.info(
                    "Queue1 hourly recovery updated: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s hour=%s",
                    location_id,
                    home_gateway_id,
                    aisle_group_id,
                    aisle_group.aisleGroupName,
                    consumption,
                    hour_start,
                )
                continue

            HourlySiteReading.objects.create(
                associated_Site=site,
                aisle_group=aisle_group,
                leg_id=aisle_group_id,
                unit_consumption=consumption,
                hourly_baseline_value=hourly_baseline,
                energy_saved=saving,
                reading_from=hour_start,
                reading_to=hour_end,
                is_visible=True,
            )
            logger.info(
                "Queue1 hourly recovery created: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s unit_consumption=%s hour=%s",
                location_id,
                home_gateway_id,
                aisle_group_id,
                aisle_group.aisleGroupName,
                consumption,
                hour_start,
            )
        mark_recovered(
            site, home_gateway_id, aisle_group, recovered_slots=len(recovery_values)
        )
    except Exception:
        logger.exception(
            "Queue1 hourly consumption recovery failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
