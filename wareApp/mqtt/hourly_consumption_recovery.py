import logging
import re
from datetime import datetime

from wareApp.models import AisleGroup, HourlySiteReading, SiteBaseline

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
    return aisle_group_id, recovery_hours.split(","), unit_consumptions.split(",")


def _hourly_baseline_for_day(location_id, aisle_group_id, observed_at):
    baseline = SiteBaseline.objects.filter(
        associated_site_id=int(location_id),
        leg_id=str(aisle_group_id),
        baseline_from__lte=observed_at.date(),
        baseline_to__gte=observed_at.date(),
    ).first()
    if not baseline:
        baseline = SiteBaseline.objects.filter(
            associated_site_id=int(location_id), leg_id=str(aisle_group_id)
        ).last()
    return baseline.baseline_value / baseline.working_hours


def handle_hourly_consumption_recovery_message(site, location_id, gateway_id, message):
    """Persist recovered hourly consumption readings for one aisle group."""
    try:
        aisle_group_id, recovery_hours, recovery_values = (
            _parse_hourly_recovery_message(message)
        )
        aisle_group = AisleGroup.objects.filter(
            site=site, attached_leg_id=aisle_group_id
        ).first()
        if not aisle_group:
            raise ValueError(f"Missing aisle group for leg {aisle_group_id}")

        for index in range(min(len(recovery_hours), len(recovery_values)) - 1):
            observed_at = datetime.strptime(
                recovery_hours[index], "%Y-%m-%d %H:%M:%S.%f"
            )
            hour_start = observed_at.replace(minute=0, second=0, microsecond=0)
            hour_end = observed_at.replace(minute=59, second=59, microsecond=0)
            consumption = (
                0.0
                if recovery_values[index] == "ERROR404"
                else float(recovery_values[index])
            )
            hourly_baseline = 0.0
            saving = 0.0
            if aisle_group.is_active:
                hourly_baseline = _hourly_baseline_for_day(
                    location_id, aisle_group_id, observed_at
                )
                saving = hourly_baseline - consumption

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
                    "Updated recovered hourly consumption for site %s, leg %s, hour %s",
                    location_id,
                    aisle_group_id,
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
                "Created recovered hourly consumption for site %s, leg %s, hour %s",
                location_id,
                aisle_group_id,
                hour_start,
            )
    except Exception:
        logger.exception(
            "Queue1 hourly consumption recovery failed for site %s from gateway %s",
            location_id,
            gateway_id,
        )
