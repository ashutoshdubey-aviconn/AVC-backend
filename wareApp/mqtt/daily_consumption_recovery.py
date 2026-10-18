import logging
import re
from datetime import datetime

from django.db import transaction

from wareApp.models import AisleGroup, DailySiteReading, SiteBaseline
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.payloads import split_paired_lists
from wareApp.mqtt.slot_writes import upsert_slots

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
    slots, values = split_paired_lists(recovery_dates, unit_consumptions, "dailyConsumption")
    return aisle_group_id, slots, values


def _baseline_for_day(location_id, aisle_group_id, observed_at):
    baseline = SiteBaseline.objects.filter(
        associated_site_id=int(location_id),
        leg_id=str(aisle_group_id),
        baseline_from__lte=observed_at,
        baseline_to__gte=observed_at,
    ).first()
    if baseline:
        return baseline.baseline_value

    baseline = (
        SiteBaseline.objects.filter(
            associated_site_id=int(location_id), leg_id=str(aisle_group_id)
        )
        .order_by("-baseline_to", "-id")
        .first()
    )
    if baseline:
        return baseline.baseline_value

    logger.warning(
        "Queue1 daily recovery baseline missing: site=%s aisle_group=%s date=%s",
        location_id,
        aisle_group_id,
        observed_at.date(),
    )
    return 0.0


def handle_daily_consumption_recovery_message(site, location_id, gateway_id, message):
    """Persist recovered daily consumption readings without lowering known values."""
    home_gateway_id = home_gateway_id_for(location_id, gateway_id)
    try:
        aisle_group_id, recovery_dates, recovery_values = _parse_daily_recovery_message(
            message
        )
        aisle_group = AisleGroup.objects.filter(
            site=site, attached_leg_id=aisle_group_id
        ).first()
        if not aisle_group:
            raise ValueError(f"Missing aisle group for leg {aisle_group_id}")

        slots = {}
        for recovery_date, recovery_value in zip(recovery_dates, recovery_values):
            observed_at = datetime.strptime(recovery_date, "%Y-%m-%d")
            consumption = 0.0 if recovery_value == "ERROR404" else float(recovery_value)
            if getattr(site, "site_type", None) == 2 and consumption > 10000:
                # Legacy guard for energy-saving sites: treat meter glitches as 0.
                consumption = 0.0
            baseline_value = 0.0
            saving = 0.0
            if aisle_group.is_active:
                baseline_value = _baseline_for_day(
                    location_id, aisle_group_id, observed_at
                )
                saving = baseline_value - consumption
            slots[observed_at.date()] = {
                "unit_consumption": consumption,
                "daily_baseline_value": baseline_value,
                "energy_saved": saving,
            }

        with transaction.atomic():
            updated, created, skipped = upsert_slots(
                DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id=aisle_group_id,
                    reading_for__in=list(slots),
                ).order_by("pk"),
                key_of=lambda row: row.reading_for,
                slots=slots,
                update_fields=["unit_consumption", "daily_baseline_value", "energy_saved"],
                build_row=lambda reading_for, values: DailySiteReading(
                    associated_Site=site,
                    aisle_group=aisle_group,
                    leg_id=aisle_group_id,
                    reading_for=reading_for,
                    is_visible=True,
                    **values,
                ),
                # Never lower a known daily value (unchanged rule).
                should_update=lambda rows, values: (
                    rows[0].unit_consumption < values["unit_consumption"]
                ),
            )
        logger.info(
            "Queue1 daily recovery applied: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s slots=%s updated=%s created=%s skipped=%s",
            location_id,
            home_gateway_id,
            aisle_group_id,
            aisle_group.aisleGroupName,
            len(slots),
            updated,
            created,
            skipped,
        )
    except Exception:
        logger.exception(
            "Queue1 daily consumption recovery failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
