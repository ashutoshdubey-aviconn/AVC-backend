import requests
from datetime import datetime, timedelta
import time
import sys
import os
#package_path = os.path.join('..','..','test_project')
#sys.path.append(package_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from wareApp.models import *

def fetch_fuel_data(start_time, end_time):
    header = {
        'Authorization' : 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3NDk2MjgzMzcsIm5iZiI6MTc0OTYyODMzNywianRpIjoiZTI5MGVjMjctOTEzNi00MGRiLTk0ODItMDdiMjU4NGY2YWM0IiwiZXhwIjoxNzQ5ODg3NTM3LCJpZGVudGl0eSI6eyJpZCI6Nzg0NDYsImRiIjowLCJjbyI6MSwibmFtZSI6IkF2aWNvbm4iLCJ0eXBlIjoiYWRtaW4iLCJyZWFkX29ubHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.ZfOeqnbPaS8F3rfPb8oHeE-EbAksGBe6ona1wZOZbio'
    }

    start_time , end_time = start_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z', end_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    api = f'https://api-track-py.roadcast.co.in/api/v1/auth/reports/fuel?start={start_time}&end={end_time}&timezone_offset=-330&variation=0&driver_ids=281311&selected_date=2024-09-13T10:29:09.528Z&device_ids=301111&selectedUserId=78446'


    data = requests.get(
        api,
        headers = header
    ).json()
    print(data['data'][0]['fuel_data'])
    return data['data'][0]['fuel_data']
    ...

def fetch_fuel_and_update_database(start_time, end_time, site_id):
    site = Site.objects.filter(id = site_id)[0]
    data = fetch_fuel_data(start_time, end_time)
    for i in data:
        print(i['@timestamp'], i['fuel'])
        epoch = int(datetime.strptime(i['@timestamp'], "%Y-%m-%d %H:%M:%S").timestamp()) * 1000
        print(epoch, i['fuel'])
        DgFuelConsumptionData.objects.get_or_create(site=site, vehicle_number=281311,
                                                                     fuel_consumption=i['fuel'],
                                                                     epoch_time=epoch, created=datetime.strptime(i['@timestamp'], "%Y-%m-%d %H:%M:%S"))


def main():
    start_time = input('enter the start date (yyyy-mm-dd) : ')
    end_time = input('enter the ending date (yyyy-mm-dd) : ')
    start_time, end_time = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S') , datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
    print(end_time, start_time, 124)
    fetch_fuel_and_update_database(start_time ,end_time, 118)

main()
