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

import logging
import traceback

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

def process_hourly(
    site,
    gateway_id,
    location_id,
    message,
):
    """
    Hourly Recovery

    TODO:
        Move existing MQTT hourly recovery block here
        WITHOUT changing any business logic.
    """

    logger.info(
        "Hourly Recovery Started | Gateway=%s",
        gateway_id,
    )

    return {
        "status": True,
        "gateway_id": gateway_id,
        "type": "hourlyConsumption",
        "message": "Hourly recovery placeholder",
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