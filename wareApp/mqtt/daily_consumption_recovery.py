import logging
import re
from datetime import datetime

from wareApp.models import AisleGroup, DailySiteReading, SiteBaseline

logger = logging.getLogger(__name__)


def _parse_daily_recovery_message(message):
    match = re.search(
        r"Aisle_group_id : (.*); Recovery_Dates : (.*); Unit_consumptions : (.*);"
        r" GW_Total_cumulative : (.*)",
        message,
    )
    if not match:
        raise ValueError("Invalid dailyConsumption recovery payload")

    aisle_group_id, recovery_dates, unit_consumptions, _ = match.groups()
    return (
        aisle_group_id,
        [value for value in recovery_dates.split(",") if value],
        [value for value in unit_consumptions.split(",") if value],
    )


def _baseline_for_day(location_id, aisle_group_id, observed_at):
    baseline = SiteBaseline.objects.filter(
        associated_site_id=int(location_id),
        leg_id=str(aisle_group_id),
        baseline_from__lte=observed_at,
        baseline_to__gte=observed_at,
    ).first()
    if baseline:
        return baseline.baseline_value

    return (
        SiteBaseline.objects.filter(
            associated_site_id=int(location_id), leg_id=str(aisle_group_id)
        ).order_by("-baseline_to", "-id").first()
        .baseline_value
    )


def handle_daily_consumption_recovery_message(site, location_id, gateway_id, message):
    """Persist recovered daily consumption readings without lowering known values."""
    try:
        aisle_group_id, recovery_dates, recovery_values = _parse_daily_recovery_message(
            message
        )
        aisle_group = AisleGroup.objects.filter(
            site=site, attached_leg_id=aisle_group_id
        ).first()
        if not aisle_group:
            raise ValueError(f"Missing aisle group for leg {aisle_group_id}")

        for recovery_date, recovery_value in zip(recovery_dates, recovery_values):
            observed_at = datetime.strptime(recovery_date, "%Y-%m-%d")
            consumption = (
                0.0
                if recovery_value == "ERROR404"
                else float(recovery_value)
            )
            baseline_value = 0.0
            saving = 0.0
            if aisle_group.is_active:
                baseline_value = _baseline_for_day(
                    location_id, aisle_group_id, observed_at
                )
                saving = baseline_value - consumption

            daily_entries = DailySiteReading.objects.filter(
                associated_Site=site,
                leg_id=aisle_group_id,
                reading_for=observed_at,
            )
            daily_record = daily_entries.first()
            if daily_record:
                if daily_record.unit_consumption < consumption:
                    daily_entries.update(
                        unit_consumption=consumption,
                        daily_baseline_value=baseline_value,
                        energy_saved=saving,
                    )
                    logger.info(
                        "Updated recovered daily consumption for site %s, leg %s, date %s",
                        location_id,
                        aisle_group_id,
                        observed_at.date(),
                    )
                continue

            DailySiteReading.objects.create(
                associated_Site=site,
                aisle_group=aisle_group,
                leg_id=aisle_group_id,
                unit_consumption=consumption,
                daily_baseline_value=baseline_value,
                energy_saved=saving,
                reading_for=observed_at,
                is_visible=True,
            )
            logger.info(
                "Created recovered daily consumption for site %s, leg %s, date %s",
                location_id,
                aisle_group_id,
                observed_at.date(),
            )
    except Exception:
        logger.exception(
            "Queue1 daily consumption recovery failed for site %s from gateway %s",
            location_id,
            gateway_id,
        )
