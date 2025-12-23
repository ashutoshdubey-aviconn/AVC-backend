import requests
import datetime

import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')
django.setup()
from datetime import date, time
from wareApp.models import *
#import time

SITE_ID = int(input("enter the Site Id : "))
site = Site.objects.filter(id = SITE_ID)
month = int(input("enter the month : "))


def call_api_for_date(date_obj):
    from_time = datetime.combine(date_obj, time.min)
    to_time = datetime.combine(date_obj, time.max).replace(microsecond=0)
    from_time_str = from_time.strftime("%Y-%m-%dT%H:%M:%S")
    to_time_str = to_time.strftime("%Y-%m-%dT%H:%M:%S")

    url = f'https://test-track.roadcast.net/api/v1/auth/pull_fuel_report?device_imei=353691840557010&from_time={from_time_str}&to_time{to_time_str}'
    params = {
        "start": from_time_str + '.000Z',
        "end": to_time_str + '.000Z',
        "device_ids" : "322105" 
    }
    headers = {
        "Authorization": "Basic QXZpY29ubjpBYmNAMTIzNA=="
    }
    response = requests.get(url, params=params, headers = headers)
    #print(response.text)
    res = dict(response.json())
    #print(res.keys())
    print(params)
    print(response)
    try:
        return res['data'][0]['consumed_fuel']
    except Exception as err:
        print("got the exception : ",err)
        return 0



d = DailySiteReading.objects.filter(associated_Site_id = SITE_ID, leg_id = 890, unit_consumption__gt = 30, reading_for__range = (date(2025, month, 1), date(2025, month, 30)))

for i in d:
    current_date = i.reading_for
    fuel_consumed = call_api_for_date(current_date)
    print(f'for {current_date}, the DG units consumed were {i.unit_consumption} and the fuel consumed is {fuel_consumed}')
    h = HourlySiteReading.objects.filter(unit_consumption__gt = 0, associated_Site = SITE_ID, leg_id = 890, reading_from__date = current_date).last().reading_to
    continue
    if(fuel_consumed > 0):
        DgUnitConsumption.objects.create(site_id = SITE_ID, aisle_group_id = 890, unit_consumption = i.unit_consumption, dg_fuel_consumption = fuel_consumed, created = h, epoch_time = h.timestamp()*1000)
    print(h)
    print()
    print()
