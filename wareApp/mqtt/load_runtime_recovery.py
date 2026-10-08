import logging
import re
from datetime import datetime

from wareApp.models import SupplyLoadTimeShare

logger = logging.getLogger(__name__)


def _parse_load_runtime_recovery_message(message):
    match = re.search(
        r"Power_source : (.*); Recovery_hours : (.*); Recovery_load_runtime : (.*)",
        message,
    )
    if not match:
        raise ValueError("Invalid loadRuntime recovery payload")

    source, recovery_hours, recovery_values = match.groups()
    return (
        int(source),
        [value for value in recovery_hours.split(",") if value],
        [value for value in recovery_values.split(",") if value],
    )


def handle_load_runtime_recovery_message(site, location_id, gateway_id, message):
    """Apply recovered runtime readings for one gateway power source."""
    try:
        source, recovery_hours, recovery_values = _parse_load_runtime_recovery_message(
            message
        )
        source_records = SupplyLoadTimeShare.objects.filter(
            site=site, power_source=source
        )

        for recovery_hour, recovery_value in zip(recovery_hours, recovery_values):
            observed_at = datetime.strptime(
                recovery_hour, "%Y-%m-%d %H:%M:%S.%f"
            )
            runtime = (
                0
                if recovery_value == "ERROR404"
                else int(recovery_value)
            )
            if source_records.filter(reading_from=observed_at).update(
                hourly_run_time=runtime
            ):
                logger.info(
                    "Updated recovered runtime for site %s, source %s, hour %s",
                    location_id,
                    source,
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
                "Created recovered runtime for site %s, source %s, hour %s",
                location_id,
                source,
                observed_at,
            )
    except Exception:
        logger.exception(
            "Queue1 loadRuntime recovery failed for site %s from gateway %s",
            location_id,
            gateway_id,
        )
