import logging
import re
from datetime import datetime

from wareApp.models import SupplyLoadTimeShare
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.payloads import split_paired_lists

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
        source_records = SupplyLoadTimeShare.objects.filter(
            site=site, power_source=source
        )

        for recovery_hour, recovery_value in zip(recovery_hours, recovery_values):
            observed_at = datetime.strptime(recovery_hour, "%Y-%m-%d %H:%M:%S.%f")
            runtime = 0 if recovery_value == "ERROR404" else int(recovery_value)
            if source_records.filter(reading_from=observed_at).update(
                hourly_run_time=runtime
            ):
                logger.info(
                    "Queue1 runtime recovery updated: site=%s home_gateway_id=%s source=%s runtime=%s hour=%s",
                    location_id,
                    home_gateway_id,
                    source,
                    runtime,
                    observed_at,
                )
                continue

            SupplyLoadTimeShare.objects.create(
                site=site,
                power_source=source,
                hourly_run_time=runtime,
                reading_from=observed_at,
                reading_to=observed_at.replace(minute=59, second=59),
            )
            logger.info(
                "Queue1 runtime recovery created: site=%s home_gateway_id=%s source=%s runtime=%s hour=%s",
                location_id,
                home_gateway_id,
                source,
                runtime,
                observed_at,
            )
    except Exception:
        logger.exception(
            "Queue1 loadRuntime recovery failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
