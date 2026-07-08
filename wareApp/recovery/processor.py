"""
Recovery Processor

This module acts as a common entry point for all recovery requests.

Recovery can come from:
    1. MQTT (existing)
    2. HTTP API (new)

Both transports should eventually call the same processing functions.

Author:
    Aviconn Recovery Refactor
"""

import re
import logging
from datetime import datetime
import traceback

from wareApp.models import (
    AisleGroup,
    HourlySiteReading,
    SiteBaseline,
)

logger = logging.getLogger(__name__)


def process_http_recovery(
    site,
    gateway_id,
    location_id,
    msg_type,
    msg_subtype,
    message,
):
    """
    Common Recovery Dispatcher

    Parameters
    ----------
    site : Site Object
    gateway_id : str
    location_id : int
    msg_type : str
    msg_subtype : str
    message : str

    Returns
    -------
    dict
    """

    try:

        logger.info(
            "HTTP Recovery Request | Gateway=%s | Site=%s | Type=%s | Subtype=%s",
            gateway_id,
            location_id,
            msg_type,
            msg_subtype,
        )

        if "dailyConsumption" in msg_subtype:

            return process_daily(
                site=site,
                gateway_id=gateway_id,
                location_id=location_id,
                message=message,
            )

        elif "hourlyConsumption" in msg_subtype:

            return process_hourly(
                site=site,
                gateway_id=gateway_id,
                location_id=location_id,
                message=message,
            )

        elif "loadRuntime" in msg_subtype:

            return process_runtime(
                site=site,
                gateway_id=gateway_id,
                location_id=location_id,
                message=message,
            )

        else:

            logger.warning(
                "Unknown Recovery Type : %s",
                msg_subtype,
            )

            return {
                "status": False,
                "message": "Unknown Recovery Type",
                "gateway_id": gateway_id,
                "subtype": msg_subtype,
            }

    except Exception as e:

        logger.exception("Recovery Dispatcher Failed")

        return {
            "status": False,
            "gateway_id": gateway_id,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# DAILY RECOVERY


def process_daily(
    site,
    gateway_id,
    location_id,
    message,
):
    """
    Daily Recovery

    TODO:
        Move existing MQTT daily recovery block here
        WITHOUT changing any business logic.
    """

    logger.info(
        "Daily Recovery Started | Gateway=%s",
        gateway_id,
    )

    return {
        "status": True,
        "gateway_id": gateway_id,
        "type": "dailyConsumption",
        "message": "Daily recovery placeholder",
    }


# HOURLY RECOVERY

logger = logging.getLogger(__name__)


def process_hourly(
    site,
    gateway_id,
    location_id,
    message,
):

    logger.info(
        "Starting hourly recovery | Site=%s | Gateway=%s",
        location_id,
        gateway_id,
    )

    created = 0
    updated = 0
    failed = 0

    try:

        aisle_group_id, recovery_hours, unit_consumptions, gw_total_cumulative = re.search(
            r"Aisle_group_id : (.*); Recovery_Hours : (.*); Unit_consumptions : (.*); GW_total_cumulative : (.*)",
            message,
        ).groups()

        hours = recovery_hours.split(",")
        hourly_consumptions = unit_consumptions.split(",")

        aisle_group = AisleGroup.objects.filter(
            site=site,
            attached_leg_id=aisle_group_id,
        )

        if not aisle_group.exists():

            return {
                "status": False,
                "message": "Aisle Group Not Found",
                "aisle_group": aisle_group_id,
            }

        aisle = aisle_group.first()

        aisle_group_active = aisle.is_active

        for i in range(len(hours) - 1):

            try:

                dateHour = datetime.strptime(
                    hours[i],
                    "%Y-%m-%d %H:%M:%S.%f",
                )

                lower = dateHour.replace(
                    minute=0,
                    second=0,
                    microsecond=0,
                )

                upper = dateHour.replace(
                    minute=59,
                    second=59,
                    microsecond=0,
                )

                if hourly_consumptions[i] == "ERROR404":

                    hourly_unit_consumption = 0.0

                else:

                    hourly_unit_consumption = float(
                        hourly_consumptions[i]
                    )

                hourly_saving = 0.0
                leg_hourly_baseline = 0.0

                if aisle_group_active:

                    baseline = SiteBaseline.objects.filter(
                        associated_site_id=int(location_id),
                        leg_id=str(aisle_group_id),
                        baseline_from__lte=dateHour.date(),
                        baseline_to__gte=dateHour.date(),
                    )

                    if baseline.exists():

                        baseline = baseline.first()

                    else:

                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=int(location_id),
                            leg_id=str(aisle_group_id),
                        ).last()

                    if baseline:

                        leg_hourly_baseline = (
                            baseline.baseline_value
                            / baseline.working_hours
                        )

                        hourly_saving = (
                            leg_hourly_baseline
                            - hourly_unit_consumption
                        )

                entry = HourlySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id=aisle_group_id,
                    reading_from=lower,
                    reading_to=upper,
                )

                if entry.exists():

                    entry.update(
                        unit_consumption=hourly_unit_consumption,
                        hourly_baseline_value=leg_hourly_baseline,
                        energy_saved=hourly_saving,
                    )

                    updated += 1

                else:

                    HourlySiteReading.objects.create(
                        associated_Site=site,
                        aisle_group=aisle,
                        leg_id=aisle_group_id,
                        unit_consumption=hourly_unit_consumption,
                        hourly_baseline_value=leg_hourly_baseline,
                        energy_saved=hourly_saving,
                        reading_from=lower,
                        reading_to=upper,
                        is_visible=True,
                    )

                    created += 1

            except Exception:

                failed += 1

                logger.exception(
                    "Failed Hour Recovery %s",
                    hours[i],
                )

        logger.info(
            "Recovery Complete | Created=%s Updated=%s Failed=%s",
            created,
            updated,
            failed,
        )

        return {
            "status": True,
            "gateway_id": gateway_id,
            "site_id": location_id,
            "aisle_group": aisle_group_id,
            "created": created,
            "updated": updated,
            "failed": failed,
        }

    except Exception as e:

        logger.exception("Hourly Recovery Failed")

        return {
            "status": False,
            "error": str(e),
        }

# LOAD RUNTIME RECOVERY


def process_runtime(
    site,
    gateway_id,
    location_id,
    message,
):
    """
    Load Runtime Recovery

    TODO:
        Move existing MQTT runtime recovery block here
        WITHOUT changing any business logic.
    """

    logger.info(
        "Runtime Recovery Started | Gateway=%s",
        gateway_id,
    )

    return {
        "status": True,
        "gateway_id": gateway_id,
        "type": "loadRuntime",
        "message": "Runtime recovery placeholder",
    }
