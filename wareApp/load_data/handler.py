from datetime import datetime, timedelta
import math

from wareApp.models import *
from wareApp.load_data.monthly import update_monthly_min_max_load
from wareApp.load_data.parser import parse_load_data_message
from wareApp.load_data.raw import save_raw_load_reading
from wareApp.load_data.rollups import roll_up_load_data_if_due


def _handle_load_data_message(client, site, location_id, gw_id, message, msg_type):
    if "LoadData" in msg_type:
        print("inside load data")
        reading = parse_load_data_message(message)
        load_value = reading.load_value
        print("load_value : ", load_value)
        load_leg_id = reading.leg_id
        print("load_leg_id", load_leg_id)
        meter_number = reading.meter_number
        print("meter_number : ", meter_number)
        print("@@@@@@@@@@@@@@@@@@@")
        load_date = reading.created
        print("load_date : ", load_date)
        load_hour = load_date.hour
        load_minute = load_date.minute
        load_epoch_time = reading.epoch_time
        print("epoch", load_epoch_time)
        load_aisle_group = AisleGroup.objects.filter(
            site=site, attached_leg_id=str(load_leg_id)
        )
        print("load_aisle_group :", load_aisle_group)
        # raw load data logic starts here
        save_raw_load_reading(site, load_aisle_group[0], reading)
        print(
            "raw entry created for {} site with leg id {} of load value {} at {}".format(
                location_id, load_leg_id, load_value, datetime.now()
            )
        )
        # raw load data logic ends here
        if site.is_loadGraph_visible:
            update_monthly_min_max_load(site, load_aisle_group[0], reading)
        roll_up_load_data_if_due(site, load_date)
        return

        # load hourly logic starts here
        previous_minute = load_date - timedelta(minutes=1)
        print("previous minute: ", previous_minute)
        if (
            load_date.date() == previous_minute.date()
            and load_date.hour == previous_minute.hour
        ):
            print("checking hourly entry for current data")
            try:
                load_hourly = HourlyLoadData.objects.filter(
                    site=site,
                    created__date=load_date.date(),
                    created__hour=load_hour,
                    created__minute=load_minute - 1,
                )
                if not load_hourly.exists():
                    print(
                        "Trying to create min, max load hourly  entry of {} minute, {} hour of site {} , aisle group {} at {}".format(
                            load_minute,
                            load_hour,
                            locationId,
                            load_leg_id,
                            datetime.now(),
                        )
                    )
                    all_leg_id = AisleGroup.objects.filter(site=site)
                    min_epoch_time = load_epoch_time
                    max_epoch_time = load_epoch_time
                    min_created = load_date
                    max_created = load_date
                    for leg in all_leg_id:
                        raw_load = RawLoadData.objects.filter(
                            site=site,
                            aisle_group=leg.id,
                            created__date=load_date.date(),
                            created__hour=load_hour,
                            created__minute=load_minute - 1,
                        )

                        if raw_load.exists():
                            min_load = math.inf
                            max_load = 0.0
                            if raw_load.exists():
                                for i in raw_load:
                                    load = i.load_data
                                    if min_load > load:
                                        min_load = load
                                        min_epoch_time = i.epoch_time
                                        min_created = i.created
                                    elif min_load == 0.0:
                                        min_load = load
                                        min_epoch_time = i.epoch_time
                                        min_created = i.created
                                    if max_load < load:
                                        max_load = load
                                        max_epoch_time = i.epoch_time
                                        max_created = i.created
                                try:
                                    if int(min_epoch_time) < int(max_epoch_time):
                                        HourlyLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=min_load,
                                            created=min_created,
                                            epoch_time=min_epoch_time,
                                        )
                                        print(
                                            "Hourly entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                min_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )
                                        HourlyLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=max_load,
                                            created=max_created,
                                            epoch_time=max_epoch_time,
                                        )
                                        print(
                                            "Hourly entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                                max_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )

                                        MainsDgLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=min_load,
                                            created=min_created,
                                            epoch_time=min_epoch_time,
                                        )
                                        print(
                                            "Mains Dg Load data entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                min_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )
                                        MainsDgLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=max_load,
                                            created=max_created,
                                            epoch_time=max_epoch_time,
                                        )
                                        print(
                                            "Mains Dg Load data entry created successfull for maximum load {} of {} site with leg id {}  at {}".format(
                                                min_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )
                                    else:
                                        HourlyLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=max_load,
                                            created=max_created,
                                            epoch_time=max_epoch_time,
                                        )
                                        print(
                                            "Hourly entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                                max_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )

                                        HourlyLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=min_load,
                                            created=min_created,
                                            epoch_time=min_epoch_time,
                                        )
                                        print(
                                            "Hourly entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                min_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )

                                        MainsDgLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=max_load,
                                            created=max_created,
                                            epoch_time=max_epoch_time,
                                        )
                                        print(
                                            "Mains Dg Load data entry created successfull for maximum load {} of {} site with leg id {}  at {}".format(
                                                min_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )
                                        MainsDgLoadData.objects.create(
                                            site=site,
                                            aisle_group=leg,
                                            load_data=min_load,
                                            created=min_created,
                                            epoch_time=min_epoch_time,
                                        )
                                        print(
                                            "Mains Dg Load data entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                min_load,
                                                locationId,
                                                leg.aisleGroupName,
                                                datetime.now(),
                                            )
                                        )

                                except Exception as err:
                                    print(
                                        "Error while storing load data in mains dg table",
                                        err,
                                    )
                        else:
                            print(
                                "storing zero load data in mains dg table for leg {} of site {} at {}".format(
                                    locationId, leg.aisleGroupName, datetime.now()
                                )
                            )
                            if int(min_epoch_time) < int(max_epoch_time):
                                MainsDgLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    load_data=0,
                                    created=min_created,
                                    epoch_time=min_epoch_time,
                                )
                                print(
                                    "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )
                                MainsDgLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    load_data=0,
                                    created=max_created,
                                    epoch_time=max_epoch_time,
                                )
                                print(
                                    "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )
                            else:
                                MainsDgLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    load_data=0,
                                    created=max_created,
                                    epoch_time=max_epoch_time,
                                )
                                print(
                                    "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )
                                MainsDgLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    load_data=0,
                                    created=min_created,
                                    epoch_time=min_epoch_time,
                                )
                                print(
                                    "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )

            except Exception as err:
                print("Error in hourly load data: ", err)
        else:
            print("else code is running for hourly load entry")
            if load_date.minute == 0:
                print("creating entry for  last minute of previous hour")
                try:
                    if previous_minute.hour == 23 and previous_minute.minute == 59:
                        print("creating last minute entry of previous day")
                        load_hourly = HourlyLoadData.objects.filter(
                            site=site,
                            created__date=previous_minute.date(),
                            created__hour=previous_minute.hour,
                            created__minute=59,
                        )
                    else:
                        print("creating last minute entry of current day")
                        load_hourly = HourlyLoadData.objects.filter(
                            site=site,
                            created__date=load_date.date(),
                            created__hour=load_date.hour - 1,
                            created__minute=59,
                        )
                    if not load_hourly.exists():
                        print(
                            "Trying to create min, max load hourly  entry of {} minute, {} hour of site {} , aisle group {} at {}".format(
                                load_minute,
                                load_hour,
                                locationId,
                                load_leg_id,
                                datetime.now(),
                            )
                        )
                        min_epoch_time = load_epoch_time
                        max_epoch_time = load_epoch_time
                        min_created = load_date
                        max_created = load_date
                        all_leg_id = AisleGroup.objects.filter(site=site)
                        for leg in all_leg_id:
                            if (
                                previous_minute.hour == 23
                                and previous_minute.minute == 59
                            ):
                                raw_load = RawLoadData.objects.filter(
                                    site=site,
                                    aisle_group=leg.id,
                                    created__date=previous_minute.date(),
                                    created__hour=previous_minute.hour,
                                    created__minute=59,
                                )
                            else:
                                raw_load = RawLoadData.objects.filter(
                                    site=site,
                                    aisle_group=leg.id,
                                    created__date=load_date.date(),
                                    created__hour=load_date.hour - 1,
                                    created__minute=59,
                                )

                            if raw_load.exists():
                                min_load = math.inf
                                max_load = 0.0
                                if raw_load.exists():
                                    for i in raw_load:
                                        load = i.load_data
                                        if min_load > load:
                                            min_load = load
                                            min_epoch_time = i.epoch_time
                                            min_created = i.created
                                        elif min_load == 0.0:
                                            min_load = load
                                            min_epoch_time = i.epoch_time
                                            min_created = i.created
                                        if max_load < load:
                                            max_load = load
                                            max_epoch_time = i.epoch_time
                                            max_created = i.created
                                    try:
                                        if int(min_epoch_time) < int(max_epoch_time):
                                            HourlyLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=min_load,
                                                created=min_created,
                                                epoch_time=min_epoch_time,
                                            )
                                            print(
                                                "Hourly entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                    min_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )
                                            HourlyLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=max_load,
                                                created=max_created,
                                                epoch_time=max_epoch_time,
                                            )
                                            print(
                                                "Hourly entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                                    max_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )

                                            MainsDgLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=min_load,
                                                created=min_created,
                                                epoch_time=min_epoch_time,
                                            )
                                            print(
                                                "Mains Dg Load data entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                    min_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )
                                            MainsDgLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=max_load,
                                                created=max_created,
                                                epoch_time=max_epoch_time,
                                            )
                                            print(
                                                "Mains Dg Load data entry created successfull for maximum load {} of {} site with leg id {}  at {}".format(
                                                    min_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )
                                        else:
                                            HourlyLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=max_load,
                                                created=max_created,
                                                epoch_time=max_epoch_time,
                                            )
                                            print(
                                                "Hourly entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                                    max_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )
                                            HourlyLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=min_load,
                                                created=min_created,
                                                epoch_time=min_epoch_time,
                                            )
                                            print(
                                                "Hourly entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                    min_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )

                                            MainsDgLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=max_load,
                                                created=max_created,
                                                epoch_time=max_epoch_time,
                                            )
                                            print(
                                                "Mains Dg Load data entry created successfull for maximum load {} of {} site with leg id {}  at {}".format(
                                                    min_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )
                                            MainsDgLoadData.objects.create(
                                                site=site,
                                                aisle_group=leg,
                                                load_data=min_load,
                                                created=min_created,
                                                epoch_time=min_epoch_time,
                                            )
                                            print(
                                                "Mains Dg Load data entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                                    min_load,
                                                    locationId,
                                                    leg.aisleGroupName,
                                                    datetime.now(),
                                                )
                                            )

                                    except Exception as err:
                                        print(
                                            "Error while storing load data in mains dg table",
                                            err,
                                        )
                            else:
                                print(
                                    "storing zero load data in mains dg table for leg {} of site {} at {}".format(
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )
                                if int(min_epoch_time) < int(max_epoch_time):
                                    MainsDgLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        load_data=0,
                                        created=min_created,
                                        epoch_time=min_epoch_time,
                                    )
                                    print(
                                        "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )
                                    MainsDgLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        load_data=0,
                                        created=max_created,
                                        epoch_time=max_epoch_time,
                                    )
                                    print(
                                        "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )
                                else:
                                    MainsDgLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        load_data=0,
                                        created=max_created,
                                        epoch_time=max_epoch_time,
                                    )
                                    print(
                                        "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )
                                    MainsDgLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        load_data=0,
                                        created=min_created,
                                        epoch_time=min_epoch_time,
                                    )
                                    print(
                                        "Mains Dg Load data entry created successfull for zero  load  of {} site with leg id {}  at {}".format(
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )
                except Exception as err:
                    print("Error in hourly load data: ", err)

            print("remaining code comes here for base case")
            pass

        # load hourly logic ends here
        # daily load data logic starts here
        previous_hour = load_date - timedelta(hours=1)
        print("previous_hour: ", previous_hour)
        if load_date.date() == previous_hour.date():
            print("checking daily entry for current data")
            try:
                load_daily_entry = DailyLoadData.objects.filter(
                    site=site,
                    created__date=load_date.date(),
                    created__hour=load_hour - 1,
                )
                if not load_daily_entry.exists():
                    print(
                        "Trying to create min, max load daily  entry of {} minute, {} hour of site {} , aisle group {} at {}".format(
                            load_minute,
                            load_hour,
                            locationId,
                            load_leg_id,
                            datetime.now(),
                        )
                    )
                    all_leg_id = AisleGroup.objects.filter(site=site)
                    for leg in all_leg_id:
                        load_hourly_entry = HourlyLoadData.objects.filter(
                            site=site,
                            aisle_group=leg.id,
                            created__date=load_date.date(),
                            created__hour=load_hour - 1,
                        )
                        if load_hourly_entry.exists():
                            min_load = math.inf
                            max_load = 0.0
                            min_epoch_time = load_epoch_time
                            max_epoch_time = load_epoch_time
                            min_created = load_date
                            max_created = load_date
                            for i in load_hourly_entry:
                                load = i.load_data
                                if min_load > load:
                                    min_load = load
                                    min_epoch_time = i.epoch_time
                                    min_created = i.created
                                elif min_load == 0.0:
                                    min_load = load
                                    min_epoch_time = i.epoch_time
                                    min_created = i.created
                                if max_load < load:
                                    max_load = load
                                    max_epoch_time = i.epoch_time
                                    max_created = i.created
                            if int(min_epoch_time) < int(max_epoch_time):
                                DailyLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    created=min_created,
                                    load_data=min_load,
                                    epoch_time=min_epoch_time,
                                )
                                print(
                                    "Daily entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                        min_load,
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )
                                DailyLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    created=max_created,
                                    load_data=max_load,
                                    epoch_time=max_epoch_time,
                                )
                                print(
                                    "Daily entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                        max_load,
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )
                            else:
                                DailyLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    created=max_created,
                                    load_data=max_load,
                                    epoch_time=max_epoch_time,
                                )
                                print(
                                    "Daily entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                        max_load,
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )
                                DailyLoadData.objects.create(
                                    site=site,
                                    aisle_group=leg,
                                    created=min_created,
                                    load_data=min_load,
                                    epoch_time=min_epoch_time,
                                )
                                print(
                                    "Daily entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                        min_load,
                                        locationId,
                                        leg.aisleGroupName,
                                        datetime.now(),
                                    )
                                )

            except Exception as err:
                print("Error in daily load data: ", err)
        else:
            if load_date.hour == 0:
                print("creating previous day last hour entry")
                try:
                    load_daily_entry = DailyLoadData.objects.filter(
                        site=site,
                        created__date=previous_hour.date(),
                        created__hour=23,
                    )
                    if not load_daily_entry.exists():
                        print(
                            "Trying to create min, max load daily  entry of {} minute, {} hour of site {} , aisle group {} at {}".format(
                                load_minute,
                                load_hour,
                                locationId,
                                load_leg_id,
                                datetime.now(),
                            )
                        )
                        all_leg_id = AisleGroup.objects.filter(site=site)
                        for leg in all_leg_id:
                            load_hourly_entry = HourlyLoadData.objects.filter(
                                site=site,
                                aisle_group=leg.id,
                                created__date=previous_hour.date(),
                                created__hour=23,
                            )
                            if load_hourly_entry.exists():
                                min_load = math.inf
                                max_load = 0.0
                                min_epoch_time = load_epoch_time
                                max_epoch_time = load_epoch_time
                                min_created = load_date
                                max_created = load_date
                                for i in load_hourly_entry:
                                    load = i.load_data
                                    if min_load > load:
                                        min_load = load
                                        min_epoch_time = i.epoch_time
                                        min_created = i.created
                                    elif min_load == 0.0:
                                        min_load = load
                                        min_epoch_time = i.epoch_time
                                        min_created = i.created
                                    if max_load < load:
                                        max_load = load
                                        max_epoch_time = i.epoch_time
                                        max_created = i.created

                                if int(min_epoch_time) < int(max_epoch_time):
                                    DailyLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        created=min_created,
                                        load_data=min_load,
                                        epoch_time=min_epoch_time,
                                    )
                                    print(
                                        "Daily entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                            min_load,
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )
                                    DailyLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        created=max_created,
                                        load_data=max_load,
                                        epoch_time=max_epoch_time,
                                    )
                                    print(
                                        "Daily entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                            max_load,
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )
                                else:
                                    DailyLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        created=max_created,
                                        load_data=max_load,
                                        epoch_time=max_epoch_time,
                                    )
                                    print(
                                        "Daily entry created successfull for max load {} of {} site with leg id {}  at {}".format(
                                            max_load,
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )
                                    DailyLoadData.objects.create(
                                        site=site,
                                        aisle_group=leg,
                                        created=min_created,
                                        load_data=min_load,
                                        epoch_time=min_epoch_time,
                                    )
                                    print(
                                        "Daily entry created successfull for minimum load {} of {} site with leg id {}  at {}".format(
                                            min_load,
                                            locationId,
                                            leg.aisleGroupName,
                                            datetime.now(),
                                        )
                                    )

                except Exception as err:
                    print("Error in daily load data: ", err)
            print("remaining code comes here")

        # daily load data logic ends here


def handle_load_data_message(client, site, location_id, gw_id, message, msg_type):
    try:
        return _handle_load_data_message(
            client, site, location_id, gw_id, message, msg_type
        )
    except Exception as err:
        print("LoadData message skipped for site {}: {}".format(location_id, err))
