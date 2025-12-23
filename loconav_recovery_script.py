import requests
import datetime
import sys
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from datetime import date, time
from wareApp.models import *


LIST_OF_SITES = [35, 76, 92]
url = 'https://marketplace.loconav.com/api/v1/vehicles/fuel'
header = {'User-Authentication' : '51uKh_YaL72s7zhx6bwZ'}

def fuel_consumed(vehical, date):
    parms = {'vehicle_number' : vehical, 'start_time' : int(datetime.combine(date, time(0,0,0)).timestamp()), 'end_time' : int(datetime.combine(date, time(23,59,59)).timestamp())}
    print(parms)
    d = requests.get(url, params = parms, headers = header)
    res = d.json()
    return res["data"]["fuel_consumption"]["value"]
    ...

for i in LIST_OF_SITES:
    a = AisleGroup.objects.filter(site_id = i, power_source = 1).last()
    print(a)
    vehical = Site.objects.get(id = i).partner_dg_fuel_id
    dates_of_consumption = DailySiteReading.objects.filter(associated_Site_id = i, aisle_group_id = a.id, leg_id = a.id, reading_for__range = (date(2024,9,1), date(2025,9,17)), unit_consumption__gt = 35)
    print(len(dates_of_consumption))
    for j in dates_of_consumption:
        d = fuel_consumed(vehical, j.reading_for)
        print(d)
        if(d != 0):
            last_hour = HourlySiteReading.objects.filter(associated_Site_id = i, aisle_group_id = a.id, leg_id = a.id, reading_from__date = j.reading_for).last()
            DgUnitConsumption.objects.update_or_create(site_id = i, aisle_group_id = a.id, created = last_hour.reading_from, epoch_time = int(last_hour.reading_from.timestamp())*1000, is_dg_on = False, fetch_fuel_data = False, defaults = {'unit_consumption' : j.unit_consumption, 'dg_fuel_consumption' : d})
            
