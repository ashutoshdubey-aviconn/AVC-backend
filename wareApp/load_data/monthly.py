from datetime import datetime

from wareApp.models import MonthlyMinMaxLoadData, SiteLoadPower

from wareApp.load_data.parser import LoadReading


def update_monthly_min_max_load(site, aisle_group, reading: LoadReading):
    power_source = aisle_group.aisleGroupName
    print("power source", power_source)
    load_entry = SiteLoadPower.objects.filter(
        Associated_Site=site.id, Meter_Number=reading.meter_number
    )
    print("load entry ", load_entry)
    print("checking for monthly min max load")
    try:
        today_date = datetime.now()
        monthly_min_max_load = MonthlyMinMaxLoadData.objects.filter(
            site=site,
            supply_source=power_source,
            created__year=today_date.year,
            created__month=today_date.month,
        )
        if monthly_min_max_load.exists():
            print("checking update for min max of monthly load data")
            monthly_min_load = monthly_min_max_load[0].min_load
            monthly_max_load = monthly_min_max_load[0].max_load
            print(
                "monthly_min_load: ",
                monthly_min_load,
                "monthly_max_load: ",
                monthly_max_load,
                "current load: ",
                reading.load_value,
            )
            if monthly_min_load > reading.load_value:
                print("updating min load")
                monthly_min_max_load.update(
                    min_load=reading.load_value, min_load_created=today_date
                )
                if load_entry.exists():
                    load_entry.update(min_load=reading.load_value)
            elif monthly_min_load == 0.0:
                monthly_min_max_load.update(
                    min_load=reading.load_value, min_load_created=today_date
                )
                if load_entry.exists():
                    load_entry.update(min_load=reading.load_value)
            if monthly_max_load < reading.load_value:
                print("updating max load")
                monthly_min_max_load.update(
                    max_load=reading.load_value, max_load_created=today_date
                )
                if load_entry.exists():
                    load_entry.update(max_load=reading.load_value)
        else:
            print("creating first entry for this month")
            MonthlyMinMaxLoadData.objects.create(
                site=site,
                min_load=reading.load_value,
                max_load=reading.load_value,
                min_load_created=today_date,
                max_load_created=today_date,
                created=today_date,
                supply_source=power_source,
            )
    except Exception as err:
        print("Error in monthly min max load section : ", err)
