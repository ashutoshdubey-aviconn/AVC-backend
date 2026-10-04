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
import time
from django.db.models import Sum
from django.db import transaction

from wareApp.models import (
    AisleGroup,
    HourlySiteReading,
    SiteBaseline,
    DailySiteReading,
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

        if "hourlyConsumption" in msg_subtype:

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


# HOURLY RECOVERY

logger = logging.getLogger(__name__)


def update_daily_from_hourly(
    site,
    aisle,
    aisle_group_id,
    reading_date,
):
    """
    Aggregate HourlySiteReading into DailySiteReading
    """

    total = (
        HourlySiteReading.objects.filter(
            associated_Site=site,
            aisle_group=aisle,
            leg_id=str(aisle_group_id),
            reading_from__date=reading_date,
        ).aggregate(total=Sum("unit_consumption"))["total"]
        or 0
    )
    baseline = SiteBaseline.objects.filter(
        associated_site_id=site.id,
        leg_id=str(aisle_group_id),
        baseline_from__lte=reading_date,
        baseline_to__gte=reading_date,
    ).first()

    if baseline is None:
        baseline = SiteBaseline.objects.filter(
            associated_site_id=site.id,
            leg_id=str(aisle_group_id),
        ).last()
    daily_baseline = 0
    daily_saving = 0

    if baseline:
        daily_baseline = baseline.baseline_value
        daily_saving = daily_baseline - total

    DailySiteReading.objects.update_or_create(
        associated_Site=site,
        aisle_group=aisle,
        leg_id=str(aisle_group_id),
        reading_for=reading_date,
        defaults={
            "unit_consumption": total,
            "daily_baseline_value": daily_baseline,
            "energy_saved": daily_saving,
            "is_visible": True,
        },
    )

    logger.info(
        "Daily Updated | Aisle=%s Date=%s Total=%s",
        aisle_group_id,
        reading_date,
        total,
    )


# def process_hourly(
#     site,
#     gateway_id,
#     location_id,
#     message,
# ):

#     logger.info(
#         "Starting hourly recovery | Site=%s | Gateway=%s",
#         location_id,
#         gateway_id,
#     )

#     created = 0
#     updated = 0
#     failed = 0
#     processed_dates = set()

#     try:

#         aisle_group_id, recovery_hours, unit_consumptions, gw_total_cumulative = (
#             re.search(
#                 r"Aisle_group_id : (.*); Recovery_Hours : (.*); Unit_consumptions : (.*); GW_total_cumulative : (.*)",
#                 message,
#             ).groups()
#         )

#         hours = recovery_hours.split(",")
#         hourly_consumptions = unit_consumptions.split(",")

#         aisle_group = AisleGroup.objects.filter(
#             site=site,
#             attached_leg_id=aisle_group_id,
#         )

#         if not aisle_group.exists():

#             return {
#                 "status": False,
#                 "message": "Aisle Group Not Found",
#                 "aisle_group": aisle_group_id,
#             }

#         aisle = aisle_group.first()

#         aisle_group_active = aisle.is_active

#         for i in range(len(hours) - 1):

#             try:

#                 dateHour = datetime.strptime(
#                     hours[i],
#                     "%Y-%m-%d %H:%M:%S.%f",
#                 )

#                 lower = dateHour.replace(
#                     minute=0,
#                     second=0,
#                     microsecond=0,
#                 )

#                 processed_dates.add(dateHour.date())

#                 upper = dateHour.replace(
#                     minute=59,
#                     second=59,
#                     microsecond=0,
#                 )

#                 if hourly_consumptions[i] == "ERROR404":

#                     hourly_unit_consumption = 0.0

#                 else:

#                     hourly_unit_consumption = float(hourly_consumptions[i])

#                 hourly_saving = 0.0
#                 leg_hourly_baseline = 0.0

#                 if aisle_group_active:

#                     baseline = SiteBaseline.objects.filter(
#                         associated_site_id=int(location_id),
#                         leg_id=str(aisle_group_id),
#                         baseline_from__lte=dateHour.date(),
#                         baseline_to__gte=dateHour.date(),
#                     )

#                     if baseline.exists():

#                         baseline = baseline.first()

#                     else:

#                         baseline = SiteBaseline.objects.filter(
#                             associated_site_id=int(location_id),
#                             leg_id=str(aisle_group_id),
#                         ).last()

#                     if baseline:

#                         leg_hourly_baseline = (
#                             baseline.baseline_value / baseline.working_hours
#                         )

#                         hourly_saving = leg_hourly_baseline - hourly_unit_consumption

#                 entry = HourlySiteReading.objects.filter(
#                     associated_Site=site,
#                     leg_id=aisle_group_id,
#                     reading_from=lower,
#                     reading_to=upper,
#                 )

#                 if entry.exists():

#                     entry.update(
#                         unit_consumption=hourly_unit_consumption,
#                         hourly_baseline_value=leg_hourly_baseline,
#                         energy_saved=hourly_saving,
#                     )

#                     updated += 1

#                 else:

#                     HourlySiteReading.objects.create(
#                         associated_Site=site,
#                         aisle_group=aisle,
#                         leg_id=aisle_group_id,
#                         unit_consumption=hourly_unit_consumption,
#                         hourly_baseline_value=leg_hourly_baseline,
#                         energy_saved=hourly_saving,
#                         reading_from=lower,
#                         reading_to=upper,
#                         is_visible=True,
#                     )

#                     created += 1

#             except Exception:

#                 failed += 1

#                 logger.exception(
#                     "Failed Hour Recovery %s",
#                     hours[i],
#                 )

#         for reading_date in processed_dates:

#             try:

#                 update_daily_from_hourly(
#                     site=site,
#                     aisle=aisle,
#                     aisle_group_id=aisle_group_id,
#                     reading_date=reading_date,
#                 )

#             except Exception:
#                 logger.exception(
#                     "Daily aggregation failed | Aisle=%s Date=%s",
#                     aisle_group_id,
#                     reading_date,
#                 )

#         logger.info(
#             "Recovery Complete | Created=%s Updated=%s Failed=%s",
#             created,
#             updated,
#             failed,
#         )

#         return {
#             "status": True,
#             "gateway_id": gateway_id,
#             "site_id": location_id,
#             "aisle_group": aisle_group_id,
#             "created": created,
#             "updated": updated,
#             "failed": failed,
#         }

#     except Exception as e:

#         logger.exception("Hourly Recovery Failed")


#         return {
#             "status": False,
#             "error": str(e),
#         }

print("=" * 80)
print("PROCESS HOURLY CALLED")
print("=" * 80)


@transaction.atomic  # for safe transaction handling
def process_hourly(
    site,
    gateway_id,
    location_id,
    message,
):

    logger.info(
        "Starting HTTP Hourly Recovery | Site=%s Gateway=%s",
        location_id,
        gateway_id,
    )

    created = 0
    updated = 0
    failed = 0

    try:

        for aisle_group_id, dates in message.items():

            aisle = AisleGroup.objects.filter(
                site=site,
                attached_leg_id=str(aisle_group_id),
            ).first()

            if not aisle:

                logger.warning(
                    "Aisle Group Not Found : %s",
                    aisle_group_id,
                )

                failed += 1
                continue

            processed_dates = set()

            aisle_group_active = aisle.is_active

            for day, hourly_data in dates.items():

                for hour, unit in hourly_data.items():

                    try:

                        dateHour = datetime.strptime(
                            f"{day} {hour}",
                            "%Y-%m-%d %H:%M",
                        )

                        processed_dates.add(dateHour.date())

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
                        if str(unit) == "ERROR404":
                            hourly_unit_consumption = 0.0
                        else:
                            hourly_unit_consumption = float(unit)

                        # hourly_saving = 0
                        # leg_hourly_baseline = 0

                        # if aisle_group_active:

                        #     baseline = SiteBaseline.objects.filter(
                        #         associated_site_id=location_id,
                        #         leg_id=str(aisle_group_id),
                        #         baseline_from__lte=dateHour.date(),
                        #         baseline_to__gte=dateHour.date(),
                        #     ).first()

                        #     if not baseline:

                        #         baseline = SiteBaseline.objects.filter(
                        #             associated_site_id=location_id,
                        #             leg_id=str(aisle_group_id),
                        #         ).last()

                        #     if baseline:

                        #         leg_hourly_baseline = (
                        #             baseline.baseline_value / baseline.working_hours
                        #         )

                        #         hourly_saving = (
                        #             leg_hourly_baseline - hourly_unit_consumption
                        #         )

                        obj, created_flag = HourlySiteReading.objects.update_or_create(
                            associated_Site=site,
                            aisle_group=aisle,
                            leg_id=str(aisle_group_id),
                            reading_from=lower,
                            reading_to=upper,
                            defaults={
                                "unit_consumption": hourly_unit_consumption,
                                "is_visible": True,
                            },
                        )

                        if created_flag:

                            created += 1

                        else:

                            updated += 1

                    except Exception:

                        failed += 1

                        logger.exception(
                            "Failed %s %s",
                            day,
                            hour,
                        )
            # Houlry processing done for this aisle group, now update daily readings
            for reading_date in processed_dates:

                update_daily_from_hourly(
                    site=site,
                    aisle=aisle,
                    aisle_group_id=aisle_group_id,
                    reading_date=reading_date,
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
