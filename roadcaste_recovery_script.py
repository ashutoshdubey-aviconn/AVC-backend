import requests
import datetime
import sys
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from datetime import date, time
from wareApp.models import *


LIST_OF_SITES = [118]
url = 'https://test-track.roadcast.net/api/v1/auth/pull_fuel_report'
header = {'Authorization' : 'Basic QXZpY29ubjpBYmNAMTIzNA=='}

def fuel_consumed(vehical, date):
    parms = {'device_imei' : vehical, 'from_time' : datetime.combine(date, time(0,0,0)).isoformat(timespec="seconds"), 'to_time' : datetime.combine(date, time(23,59,59)).isoformat(timespec="seconds")}
    print(parms)
    d = requests.get(url, params = parms, headers = header)
    res = d.json()
    try:
        return res["fuel_consumed"]
    except : 
        print(res)
        return 0
    ...

for i in LIST_OF_SITES:
    a = AisleGroup.objects.filter(site_id = i, power_source = 1).last()
    print(a)
    vehical = Site.objects.get(id = i).partner_dg_fuel_id
    dates_of_consumption = DailySiteReading.objects.filter(associated_Site_id = i, aisle_group_id = a.id, leg_id = a.id, reading_for__range = (date(2025,10,1), date(2025,11,14)), unit_consumption__gt = 35)
    print(len(dates_of_consumption))
    for j in dates_of_consumption:
        d = fuel_consumed(vehical, j.reading_for)
        print(d)
        if(d != 0):
            last_hour = HourlySiteReading.objects.filter(associated_Site_id = i, aisle_group_id = a.id, leg_id = a.id, reading_from__date = j.reading_for).last()
            DgUnitConsumption.objects.update_or_create(site_id = i, aisle_group_id = a.id, created = last_hour.reading_from, epoch_time = int(last_hour.reading_from.timestamp())*1000, is_dg_on = False, fetch_fuel_data = False, defaults = {'unit_consumption' : j.unit_consumption, 'dg_fuel_consumption' : d})
            
