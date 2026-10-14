import logging
from datetime import datetime

from wareApp.models import MonthlyMinMaxLoadData, SiteLoadPower

from wareApp.load_data.parser import LoadReading

logger = logging.getLogger(__name__)


def update_monthly_min_max_load(site, aisle_group, reading: LoadReading):
    power_source = aisle_group.aisleGroupName
    try:
        today_date = datetime.now()
        month_start = today_date.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1)
        monthly_min_max_load = MonthlyMinMaxLoadData.objects.filter(
            site=site,
            supply_source=power_source,
            created__gte=month_start,
            created__lt=next_month_start,
        )
        monthly_load = monthly_min_max_load.values("min_load", "max_load").first()
        if monthly_load:
            monthly_min_load = monthly_load["min_load"]
            monthly_max_load = monthly_load["max_load"]
            initialized_minimum = (
                monthly_min_load == 0.0 and monthly_min_load <= reading.load_value
            )
            update_minimum = (
                monthly_min_load > reading.load_value or monthly_min_load == 0.0
            )
            update_maximum = monthly_max_load < reading.load_value
            monthly_updates = {}
            site_load_updates = {}
            if update_minimum:
                monthly_updates.update(
                    min_load=reading.load_value, min_load_created=today_date
                )
                site_load_updates["min_load"] = reading.load_value
            if update_maximum:
                monthly_updates.update(
                    max_load=reading.load_value, max_load_created=today_date
                )
                site_load_updates["max_load"] = reading.load_value

            if monthly_updates:
                monthly_min_max_load.update(**monthly_updates)
                SiteLoadPower.objects.filter(
                    Associated_Site=site.id, Meter_Number=reading.meter_number
                ).update(**site_load_updates)

            if update_minimum:
                logger.info(
                    (
                        "Initialized monthly minimum load for site %s, source %s to %s"
                        if initialized_minimum
                        else "Updated monthly minimum load for site %s, source %s to %s"
                    ),
                    site.id,
                    power_source,
                    reading.load_value,
                )
            if update_maximum:
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
