import logging
import re
from datetime import datetime

from django.db import transaction

from wareApp.models import AisleGroup, HourlySiteReading
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.log_format import hour_ranges
from wareApp.mqtt.services.baseline import BaselineMemo
from wareApp.mqtt.services.failures import TRANSIENT_DB_ERRORS, record_dead_letter
from wareApp.mqtt.payloads import split_paired_lists
from wareApp.mqtt.slot_writes import upsert_slots
from wareApp.mqtt.services.recovery_status import (
    HOURLY_CONSUMPTION,
    RecoveryScope,
    RecoverySlot,
    RecoveryStatusService,
)

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
    slots, values = split_paired_lists(recovery_hours, unit_consumptions, "hourlyConsumption")
    return aisle_group_id, slots, values


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

        slots = {}
        status_slots = []
        baselines = BaselineMemo(site, aisle_group)
        for recovery_hour, recovery_value in zip(recovery_hours, recovery_values):
            observed_at = datetime.strptime(recovery_hour, "%Y-%m-%d %H:%M:%S.%f")
            hour_start = observed_at.replace(minute=0, second=0, microsecond=0)
            hour_end = observed_at.replace(minute=59, second=59, microsecond=0)
            # ERROR404: the gateway has no data for that hour; stored as 0.
            consumption = 0.0 if recovery_value == "ERROR404" else float(recovery_value)
            status_slots.append(RecoverySlot(hour_start, recovery_value == "ERROR404"))
            hourly_baseline, _ = baselines.for_day(hour_start.date())
            slots[(hour_start, hour_end)] = {
                "unit_consumption": consumption,
                "hourly_baseline_value": hourly_baseline,
                # Same rule as live packets: saving only for active aisles.
                "energy_saved": (hourly_baseline - consumption) if aisle_group.is_active else 0.0,
            }

        scope = RecoveryScope.aisle(aisle_group)
        status = RecoveryStatusService(site, home_gateway_id)
        with transaction.atomic():
            monitor = status.record_response(
                scope, HOURLY_CONSUMPTION, status_slots, message
            )
            written = upsert_slots(
                HourlySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id=aisle_group_id,
                    reading_from__in=[start for start, _ in slots],
                ),
                key_of=lambda row: (row.reading_from, row.reading_to),
                slots=slots,
                update_fields=["unit_consumption", "hourly_baseline_value", "energy_saved"],
                build_row=lambda key, values: HourlySiteReading(
                    associated_Site=site,
                    aisle_group=aisle_group,
                    leg_id=aisle_group_id,
                    reading_from=key[0],
                    reading_to=key[1],
                    is_visible=True,
                    **values,
                ),
            )
            status.record_applied(monitor, scope, status_slots)
        error_hours = [slot.start for slot in status_slots if slot.is_error]
        logger.info(
            "Queue1 hourly recovery bulk write: site=%s home_gateway_id=%s leg_id=%s aisle_group_name=%s "
            "received=%s h [%s] created=%s [%s] updated=%s [%s] error404=%s [%s] monitor_status=%s",
            location_id,
            home_gateway_id,
            aisle_group_id,
            aisle_group.aisleGroupName,
            len(slots),
            hour_ranges([start for start, _ in slots]),
            len(written.created),
            hour_ranges([start for start, _ in written.created]),
            len(written.updated),
            hour_ranges([start for start, _ in written.updated]),
            len(error_hours),
            hour_ranges(error_hours),
            monitor.status,
        )
        return (
            f"hourly recovery: {len(slots)} h received, created={len(written.created)} "
            f"updated={len(written.updated)} error404={len(error_hours)} status={monitor.status}"
        )
    except TRANSIENT_DB_ERRORS:
        raise
    except Exception as error:
        logger.exception(
            "Queue1 hourly consumption recovery failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
        record_dead_letter("recovery/hourlyConsumption", location_id, gateway_id, message, error)
        return f"failed: {type(error).__name__}: {str(error)[:80]} (dead letter)"
