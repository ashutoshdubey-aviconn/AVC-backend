import logging
import re
from datetime import datetime, timedelta

from django.db import transaction

from wareApp.models import AisleGroup, DailySiteReading
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.log_format import day_ranges
from wareApp.mqtt.services.baseline import baseline_row
from wareApp.mqtt.services.consumption_alarms import evaluate_days
from wareApp.mqtt.services.failures import TRANSIENT_DB_ERRORS, record_dead_letter
from wareApp.mqtt.payloads import split_paired_lists
from wareApp.mqtt.services.recovery_status import (
    DAILY_CONSUMPTION,
    RecoveryScope,
    RecoverySlot,
    RecoveryStatusService,
)
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
    """Daily baseline for the day (dated row first, else latest), or None."""
    row = baseline_row(location_id, aisle_group_id, observed_at.date())
    return None if row is None else row[0]


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
        status_slots = []
        baseline_missing = []
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
                if baseline_value is None:
                    baseline_missing.append(observed_at.date())
                    baseline_value = 0.0
                saving = baseline_value - consumption
            status_slots.append(RecoverySlot(observed_at, recovery_value == "ERROR404"))
            slots[observed_at.date()] = {
                "unit_consumption": consumption,
                "daily_baseline_value": baseline_value,
                "energy_saved": saving,
            }

        scope = RecoveryScope.aisle(aisle_group)
        status = RecoveryStatusService(site, home_gateway_id)
        with transaction.atomic():
            monitor = status.record_response(
                scope, DAILY_CONSUMPTION, status_slots, message, slot_length=timedelta(days=1)
            )
            written = upsert_slots(
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
            status.record_applied(monitor, scope, status_slots)
        alarms = evaluate_days(site, aisle_group, list(written.created) + list(written.updated))
        if alarms:
            logger.info(
                "Queue1 daily recovery alarms: site=%s leg_id=%s aisle_group_name=%s %s",
                location_id, aisle_group_id, aisle_group.aisleGroupName, "; ".join(alarms),
            )
        if baseline_missing:
            logger.warning(
                "Queue1 daily recovery baseline missing (stored with baseline 0): site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s days=%s [%s]",
                location_id,
                home_gateway_id,
                aisle_group_id,
                aisle_group.aisleGroupName,
                len(baseline_missing),
                day_ranges(baseline_missing),
            )
        error_days = [slot.start for slot in status_slots if slot.is_error]
        logger.info(
            "Queue1 daily recovery bulk write: site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s "
            "received=%s d [%s] created=%s [%s] updated=%s [%s] "
            "skipped=%s [%s] (stored value already >= recovered) error404=%s [%s]",
            location_id,
            home_gateway_id,
            aisle_group_id,
            aisle_group.aisleGroupName,
            len(slots),
            day_ranges(list(slots)),
            len(written.created),
            day_ranges(written.created),
            len(written.updated),
            day_ranges(written.updated),
            len(written.skipped),
            day_ranges(written.skipped),
            len(error_days),
            day_ranges(error_days),
        )
        return (
            f"daily recovery: {len(slots)} d received, created={len(written.created)} "
            f"updated={len(written.updated)} skipped={len(written.skipped)} (already >= recovered)"
        )
    except TRANSIENT_DB_ERRORS:
        raise
    except Exception as error:
        logger.exception(
            "Queue1 daily consumption recovery failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
        record_dead_letter("recovery/dailyConsumption", location_id, gateway_id, message, error)
        return f"failed: {type(error).__name__}: {str(error)[:80]} (dead letter)"
