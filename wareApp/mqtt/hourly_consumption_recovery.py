import logging
import re
from datetime import datetime

from django.db import transaction

from wareApp.models import AisleGroup, HourlySiteReading
from wareApp.mqtt.log_context import home_gateway_id_for
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
        for recovery_hour, recovery_value in zip(recovery_hours, recovery_values):
            observed_at = datetime.strptime(recovery_hour, "%Y-%m-%d %H:%M:%S.%f")
            hour_start = observed_at.replace(minute=0, second=0, microsecond=0)
            hour_end = observed_at.replace(minute=59, second=59, microsecond=0)
            # ERROR404: the gateway has no data for that hour; stored as 0.
            consumption = 0.0 if recovery_value == "ERROR404" else float(recovery_value)
            status_slots.append(RecoverySlot(hour_start, recovery_value == "ERROR404"))
            slots[(hour_start, hour_end)] = {
                "unit_consumption": consumption,
                "hourly_baseline_value": 0.0,
                "energy_saved": 0.0,
            }

        scope = RecoveryScope.aisle(aisle_group)
        status = RecoveryStatusService(site, home_gateway_id)
        with transaction.atomic():
            monitor = status.record_response(
                scope, HOURLY_CONSUMPTION, status_slots, message
            )
            updated, created, _ = upsert_slots(
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
        logger.info(
            "Queue1 hourly recovery applied: site=%s home_gateway_id=%s aisle_group=%s aisle_group_name=%s slots=%s updated=%s created=%s monitor_status=%s",
            location_id,
            home_gateway_id,
            aisle_group_id,
            aisle_group.aisleGroupName,
            len(slots),
            updated,
            created,
            monitor.status,
        )
    except Exception:
        logger.exception(
            "Queue1 hourly consumption recovery failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
