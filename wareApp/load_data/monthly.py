import logging
from datetime import datetime

from wareApp.models import MonthlyMinMaxLoadData, SiteLoadPower

from wareApp.load_data.parser import LoadReading

logger = logging.getLogger(__name__)


def update_monthly_min_max_load(site, aisle_group, reading: LoadReading):
    power_source = aisle_group.aisleGroupName
    try:
        today_date = datetime.now()
        monthly_min_max_load = MonthlyMinMaxLoadData.objects.filter(
            site=site,
            supply_source=power_source,
            created__year=today_date.year,
            created__month=today_date.month,
        )
        monthly_load = monthly_min_max_load.first()
        if monthly_load:
            monthly_min_load = monthly_load.min_load
            monthly_max_load = monthly_load.max_load
            if monthly_min_load > reading.load_value:
                monthly_min_max_load.update(
                    min_load=reading.load_value, min_load_created=today_date
                )
                SiteLoadPower.objects.filter(
                    Associated_Site=site.id, Meter_Number=reading.meter_number
                ).update(min_load=reading.load_value)
                logger.info(
                    "Updated monthly minimum load for site %s, source %s to %s",
                    site.id,
                    power_source,
                    reading.load_value,
                )
            elif monthly_min_load == 0.0:
                monthly_min_max_load.update(
                    min_load=reading.load_value, min_load_created=today_date
                )
                SiteLoadPower.objects.filter(
                    Associated_Site=site.id, Meter_Number=reading.meter_number
                ).update(min_load=reading.load_value)
                logger.info(
                    "Initialized monthly minimum load for site %s, source %s to %s",
                    site.id,
                    power_source,
                    reading.load_value,
                )
            if monthly_max_load < reading.load_value:
                monthly_min_max_load.update(
                    max_load=reading.load_value, max_load_created=today_date
                )
                SiteLoadPower.objects.filter(
                    Associated_Site=site.id, Meter_Number=reading.meter_number
                ).update(max_load=reading.load_value)
                logger.info(
                    "Updated monthly maximum load for site %s, source %s to %s",
                    site.id,
                    power_source,
                    reading.load_value,
                )
        else:
            MonthlyMinMaxLoadData.objects.create(
                site=site,
                min_load=reading.load_value,
                max_load=reading.load_value,
                min_load_created=today_date,
                max_load_created=today_date,
                created=today_date,
                supply_source=power_source,
            )
            logger.info(
                "Created monthly min/max load for site %s, source %s at %s",
                site.id,
                power_source,
                reading.load_value,
            )
    except Exception:
        logger.exception("Failed to update monthly min/max load for site %s", site.id)
