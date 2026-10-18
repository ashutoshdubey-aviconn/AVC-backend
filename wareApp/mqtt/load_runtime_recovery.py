import logging
import re
from datetime import datetime

from django.db import transaction

from wareApp.models import SupplyLoadTimeShare
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.payloads import split_paired_lists
from wareApp.mqtt.services.recovery_status import (
    LOAD_RUNTIME,
    RecoveryScope,
    RecoverySlot,
    RecoveryStatusService,
)
from wareApp.mqtt.slot_writes import upsert_slots

logger = logging.getLogger(__name__)


def _parse_load_runtime_recovery_message(message):
    match = re.search(
        r"Power_source : (.*); Recovery_hours : (.*); Recovery_load_runtime : (.*)",
        message,
    )
    if not match:
        raise ValueError("Invalid loadRuntime recovery payload")

    source, recovery_hours, recovery_values = match.groups()
    slots, values = split_paired_lists(recovery_hours, recovery_values, "loadRuntime")
    return int(source), slots, values


def handle_load_runtime_recovery_message(site, location_id, gateway_id, message):
    """Apply recovered runtime readings for one gateway power source."""
    home_gateway_id = home_gateway_id_for(location_id, gateway_id)
    try:
        source, recovery_hours, recovery_values = _parse_load_runtime_recovery_message(
            message
        )
        slots = {}
        status_slots = []
        for recovery_hour, recovery_value in zip(recovery_hours, recovery_values):
            observed_at = datetime.strptime(recovery_hour, "%Y-%m-%d %H:%M:%S.%f")
            # ERROR404: the gateway has no data for that hour; stored as 0.
            runtime = 0 if recovery_value == "ERROR404" else int(recovery_value)
            slots[observed_at] = {"hourly_run_time": runtime}
            status_slots.append(RecoverySlot(observed_at, recovery_value == "ERROR404"))

        scope = RecoveryScope.source(source)
        status = RecoveryStatusService(site, home_gateway_id)
        with transaction.atomic():
            monitor = status.record_response(scope, LOAD_RUNTIME, status_slots, message)
            updated, created, _ = upsert_slots(
                SupplyLoadTimeShare.objects.filter(
                    site=site, power_source=source, reading_from__in=list(slots)
                ),
                key_of=lambda row: row.reading_from,
                slots=slots,
                update_fields=["hourly_run_time"],
                build_row=lambda reading_from, values: SupplyLoadTimeShare(
                    site=site,
                    power_source=source,
                    reading_from=reading_from,
                    reading_to=reading_from.replace(minute=59, second=59),
                    **values,
                ),
            )
            status.record_applied(monitor, scope, status_slots)
        logger.info(
            "Queue1 runtime recovery applied: site=%s home_gateway_id=%s source=%s slots=%s updated=%s created=%s",
            location_id,
            home_gateway_id,
            source,
            len(slots),
            updated,
            created,
        )
    except Exception:
        logger.exception(
            "Queue1 loadRuntime recovery failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
