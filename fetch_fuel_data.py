import time
import os
import json
from datetime import datetime, timedelta
import sys
package_path = os.path.join('..','django_project')
sys.path.append(package_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
import psycopg2
import logging
import requests
from wareApp.models import *
#from wareApp.sendmail import send_mail_for_dg_fuel_under_level


def get_fuel_data_roadcaste():
    try:
        url = 'https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234'
        response = requests.get(url)
        data = response.json()
        for i in data.get('data'):
            print(i.get('deviceImei'))
            s = Site.objects.filter(partner_dg_fuel_id=i.get('deviceImei'))
            if not s:
                print('No Site Found')
                continue
            now = datetime.now()
            DgFuelConsumptionData.objects.create(
            site=s[0],
            fuel_consumption= 0 if i.get('fuel') == '' else int(i.get('fuel')),
            vehicle_number=i.get('deviceImei'),
            created = now,
            epoch_time = int(now.timestamp()) * 1000
            )
    except Exception as e:
        print(str(e))



def fetchDataFromRoadcasteApi():
    headers = {
  'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3bHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.Fwn08jciwxlm659ZYEfq1LpQBAf2fddUZ9zrjmrzcmU'
}
    data = requests.get(
        'https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234',
        #headers = headers
    )
    try:
        data = data.json()
        if (data):
            return data['data'][0]['fuel'], data['data'][0]['lastUpdate']
    except:
        data = data.text
        print("got a response : ", data)
        print("failed to fetch data for {datetime.now}")

def checkRefuel():
    headers = {
  'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3Mjg2Mjk0NjIsIm5iZiI6MTcyODYyOTQ2MiwianRpIjoiZjUxYjMyMGItZWM0OC00ZWQwLWIyZWMtM2JhNWRlYjcwMGU2IiwiZXhwIjoxNzI4ODg4NjYyLCJpZGVudGl0eSI6eyJpZCI6Nzg0NDYsImRiIjowLCJjbyI6MSwibmFtZSI6IkF2aWNvbm4iLCJ0eXBlIjoiYWRtaW4iLCJyZWFkX29ubHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.4eju9Peyaid-ZXOfrOT1pVUZV_Hi-ydRu68rVmRbiS4'
    }

    data = requests.get(
        'https://api-track-py.roadcast.co.in/api/v1/auth/dashboard/fuel/last_filled/sensor?device_id=281311&selectedUserId=78446',
        headers=headers
    )
    try:
        data = data.json()
        if (data):
            print(data['data']['quantity_filled'], data['data']['timestamp'])
            return data['data']['quantity_filled'], data['data']['timestamp']
    except:
        #data = data.text
        print("got a response : ", data)
        print("failed to fetch data for {datetime.now}")
        return None, None


def checkTheft():
    headers = {
            'Authorization' : 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3Mjg2Mjk0NjIsIm5iZiI6MTcyODYyOTQ2MiwianRpIjoiZjUxYjMyMGItZWM0OC00ZWQwLWIyZWMtM2JhNWRlYjcwMGU2IiwiZXhwIjoxNzI4ODg4NjYyLCJpZGVudGl0eSI6eyJpZCI6Nzg0NDYsImRiIjowLCJjbyI6MSwibmFtZSI6IkF2aWNvbm4iLCJ0eXBlIjoiYWRtaW4iLCJyZWFkX29ubHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.4eju9Peyaid-ZXOfrOT1pVUZV_Hi-ydRu68rVmRbiS4'
            }
    data = requests.get(
            'https://api-track-py.roadcast.co.in/api/v1/auth/alerts_dashboard?selectedUserId=78446',
            headers = headers
            )
    try:
        if(data):
            print(data['data']['drainage'])
            return data['data']['drainage']
        else:
            return None
    except:
        ...

def fetchDataAndUpdate(site_id):
    try:
        site = Site.objects.get(id = site_id)
        fuel_level, level_timestamp= fetchDataFromRoadcasteApi()
        fuel_refill , refill_timestamp = checkRefuel()
        fuel_theft = checkTheft()
        print(fuel_level, level_timestamp)
        print(fuel_refill , refill_timestamp)
        level_timestamp = datetime.strptime(level_timestamp,"%Y-%m-%dT%H:%M:%S.%f%z")
        date , epoch_time = level_timestamp , int(datetime.now().timestamp()) * 1000
        print(epoch_time)
        if(fuel_level):
            DgFuelConsumptionData.objects.get_or_create(site=site, vehicle_number=281311,
                                                                     fuel_consumption=fuel_level,
                                                                     epoch_time=epoch_time, created=date)
        if(fuel_refill):
            refill_timestamp = datetime.strptime(refill_timestamp,"%Y-%m-%dT%H:%M:%S.%f")
            refuel_date , refuel_epoch_time = refill_timestamp, int(refill_timestamp.timestamp())
            DGFuelAlertsData.objects.get_or_create(site=site, vehicle_number=281311,
                alert_name='refuel', epoch_time=refuel_epoch_time,
                                                                fuel_consumption=fuel_refill, created=refuel_date)

        if(fuel_theft):
            theft_timestamp = datetime.strptime(datetime.now().timestamp(),"%Y-%m-%dT%H:%M:%S.%f")
            theft_date , theft_epoch_time = theft_timestamp, int(theft_timestamp.timestamp())
            DGFuelAlertsData.objects.get_or_create(site=site, vehicle_number=281311,
                alert_name='theft', epoch_time=theft_epoch_time,
                                                                fuel_consumption=fuel_theft, created=theft_date)
    except Exception as e:
        print(e)



def fetch_interval_data():
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    start_time = 1694662200
    end_time = 1694696400  # less than 1 day
    interval = 5
    site = Site.objects.get(id=76)
    vehicle_number = "DCGenerator-01"
    data = requests.get(
        f"https://marketplace.loconav.com/api/v1/vehicles/fuel/interval_data?start_time={start_time}&end_time={end_time}&interval={interval}&vehicle_number={vehicle_number}",
        headers=headers).json()
    print(data)
    for i in data["data"]:
        epoch_time = int(i["time"])
        date = datetime.fromtimestamp(epoch_time)
        print(date, epoch_time, i["value"])
        check_exist_data = DgFuelConsumptionData.objects.filter(site=site, vehicle_number=vehicle_number,
                                                                epoch_time=epoch_time * 1000)
        if not check_exist_data.exists():
            DgFuelConsumptionData.objects.create(site=site, vehicle_number=vehicle_number, fuel_consumption=i["value"],
                                                 epoch_time=epoch_time * 1000, created=date)
        else:
            print("Entry already exist with same data set")

def fetch_real_time_data():
    print("############## api call starts at {} ###################3".format(datetime.now()))
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    site_ids = Site.objects.filter(dg_fuel_system_installed=True)
    alert_api_url = []
    if site_ids.exists():
        for site in site_ids:
            vehicle_number = site.partner_dg_fuel_id
            print("vehicle_number",vehicle_number)
            if vehicle_number:
                print(f"Fetching data for Site ID {site} and Vehicle Number {vehicle_number}")

                try:
                    # Fuel level data API call
                    start_time = datetime.now() - timedelta(hours=23)
                    start_time = int(start_time.timestamp())
                    print("start_time : ",start_time)
                    end_time = int(datetime.now().timestamp())
                    print("end_time :",end_time)
                    data = requests.get(
                        f"https://marketplace.loconav.sensorise.net/api/v1/vehicles/fuel/current_levels?vehicle_number={vehicle_number}",
                        headers=headers).json()
                    data = data["data"]
                    alert_api_url = data
                    print("data",data)

                    if len(data):
                        for i in data:
                            check_already_exists = DgFuelConsumptionData.objects.filter(site=site,
                                                                                        vehicle_number=vehicle_number,
                                                                                        epoch_time=datetime.now().timestamp()*1000)

                            if not check_already_exists.exists():
                                date = datetime.fromtimestamp(int(datetime.now().timestamp()))
                                DgFuelConsumptionData.objects.create(site=site, vehicle_number=vehicle_number,
                                                                     fuel_consumption=i["fuel_in_liters"],
                                                                     epoch_time=int(datetime.now().timestamp()*1000), created=date)
                                try:
                                    print("###: ", site.dg_fuel_minimum_level)
                                    if site.dg_fuel_minimum_level and i['fuel_in_liters'] < site.dg_fuel_minimum_level:
                                        print("$$$$$")
                                        check_alarm = NewAlarmsNotifications.objects.filter(site_id=site, alarm_type=4,  created__gte=datetime.now() - timedelta(hours=23))
                                        print("check_alarm: ", check_alarm)
                                        if not check_alarm.exists():
                                            print("generating alarms")
                                            fuel_level = (site.dg_fuel_minimum_level/site.dg_fuel_tank_capacity)*100
                                            NewAlarmsNotifications.objects.create(site_id=site, alarm_type=4, alarm_priority=0, created=datetime.now(), fuel_level=fuel_level)
                                            data = {"site_id": site.id, "vehicle_number": site.partner_dg_fuel_id, "fuel_level": fuel_level,
                                                    "tank_capacity":site.dg_fuel_tank_capacity}
                                            send_mail_for_dg_fuel_under_level(data)
                                            print("mail sent for fuel level")
                                except Exception as err:
                                    print("Error while generating alarms or sending mail", err)
                                print("Fuel data inserted successfully")
                            else:
                                print("Fuel data entry already exists")
                    else:
                        print("No fuel data from API")
                except Exception as err:
                    print(
                        f"Error while fetching fuel level data for Vehicle {vehicle_number} at Site {site}: {err} at {datetime.now()}")

                try:
                    # Alerts data API call
                    start_time = datetime.now() - timedelta(hours=23)
                    start_time = int(start_time.timestamp())
                    end_time = int(datetime.now().timestamp())
                    #if  len(alert_api_url) == 0:
                    alert_api_url = requests.get(
                        f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={start_time}&end_time={end_time}",
                        headers=headers).json()['data']

                    if 'alerts' in alert_api_url:
                        refuel_alerts = alert_api_url['alerts']["REFUELING_ALERT"]
                        theft_alerts = alert_api_url['alerts']['POSSIBLE_FUEL_THEFT_ALERT']
                        print(refuel_alerts)
                        for i in refuel_alerts:
                            check_refuel_alert_exists = DGFuelAlertsData.objects.filter(site=site,
                                                                                        vehicle_number=vehicle_number,
                                                                                        alert_name='refuel',
                                                                                        epoch_time=i['timestamp'])
                            if not check_refuel_alert_exists.exists():
                                date = datetime.fromtimestamp(int(i['timestamp']))
                                DGFuelAlertsData.objects.create(site=site, vehicle_number=vehicle_number,
                                                                alert_name='refuel', epoch_time=i['timestamp'],
                                                                fuel_consumption=i['value'], created=date)
                                print("Refuel alert inserted successfully")
                        print(theft_alerts)
                        for j in theft_alerts:
                            check_theft_alert_exists = DGFuelAlertsData.objects.filter(site=site,
                                                                                       vehicle_number=vehicle_number,
                                                                                       alert_name='theft',
                                                                                       epoch_time=j['timestamp'])
                            if not check_theft_alert_exists.exists():
                                date = datetime.fromtimestamp(int(j['timestamp']))
                                DGFuelAlertsData.objects.create(site=site, vehicle_number=vehicle_number,
                                                                alert_name='theft',
                                                                fuel_consumption=j['value'],
                                                                epoch_time=j['timestamp'],
                                                                created=date)
                                print("Theft alert inserted successfully")
                except Exception as err:
                    print(
                        f"Exception in alert data API for Vehicle {vehicle_number} at Site {site}: {err} at {datetime.now()}")
            else:
                print("Vehicle number not added for this site : ", site.id)
    print("*************** API finished at {} **************".format(datetime.now()))

def fetch_alerts_data():
    try:
        headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
        vehicle_number = "DCGenerator-01"
        site = Site.objects.get(id=76)
        start_time = 1694662200
        end_time = 1694696400
        alert_api_url = requests.get(
            f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={start_time}&end_time={end_time}",
            headers=headers).json()['data']
        # print(alert_api_url)
        if 'alerts' in alert_api_url:
            print('##################3')
            refuel_alerts = alert_api_url['alerts']["REFUELING_ALERT"]
            # print(refuel_alerts)
            theft_alerts = alert_api_url['alerts']['POSSIBLE_FUEL_THEFT_ALERT']
            for i in refuel_alerts:
                print("inside refuel: ", i)
                check_refuel_alert_exists = DGFuelAlertsData.objects.filter(site=site, vehicle_number=vehicle_number,
                                                                            alert_name='refuel',
                                                                            epoch_time=i['timestamp'])
                print("$$$$$$$$$$$$$$$$$$$$$$$$$444")
                print('check_refuel_alert_exists', check_refuel_alert_exists)
                if not check_refuel_alert_exists.exists():
                    print("inserting refuel alert in db")
                    date = datetime.fromtimestamp(int(i['timestamp']))
                    DGFuelAlertsData.objects.create(site=site, vehicle_number=vehicle_number, alert_name='refuel',
                                                    epoch_time=i['timestamp'],
                                                    fuel_consumption=i['value'], created=date)
                    print("refuel alert inserted successfully")
            for j in theft_alerts:
                check_theft_alert_exists = DGFuelAlertsData.objects.filter(site=site, vehicle_number=vehicle_number,
                                                                           alert_name='theft',
                                                                           epoch_time=j['timestamp'])
                if not check_theft_alert_exists.exists():
                    print("inserting theft alerts in db")
                    date = datetime.fromtimestamp(int(j['timestamp']))
                    DGFuelAlertsData.objects.create(site=site, vehicle_number=vehicle_number,
                                                    alert_name='theft',
                                                    fuel_consumption=j['value'],
                                                    epoch_time=j['timestamp'],
                                                    created=date)
                    print("theft alert inserted successfully")
    except Exception as err:
        print("Exception in alert data api  : ", err, ' at: ', datetime.now())


def update_dg_fuel_consumption_data():
    print("function start for updating fuel level")
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    site_ids = Site.objects.filter(dg_fuel_system_installed=True)
    alert_api_url = []
    if site_ids.exists():
        for site in site_ids:
            vehicle_number = site.partner_dg_fuel_id
            dg_data = DgUnitConsumption.objects.filter(site=site, fetch_fuel_data=True)
            if dg_data.exists():
                for i in dg_data:
                    try:
                        dg_start_date = int(i.dg_start_date.timestamp())
                        dg_end_date = int(i.dg_end_date.timestamp())
                        fetch_fuel = requests.get(
                            f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={dg_start_date}&end_time={dg_end_date}",
                            headers=headers).json()
                        if 'data' in fetch_fuel:
                            fetch_fuel = fetch_fuel["data"]
                            if 'fuel_consumption' in fetch_fuel:
                                fuel = fetch_fuel['fuel_consumption']['value']
                                i.dg_fuel_consumption = fuel
                                print("dg_fuel_consumption: ",datetime.now(),fuel)
                                i.fetch_fuel_data = False
                                i.save()
                    except Exception as err:
                        print(err)

# fetch_alerts_data()
# fetch_interval_data()

while True:
    get_fuel_data_roadcaste()
    #fetchDataAndUpdate(124)
    fetch_real_time_data()
    update_dg_fuel_consumption_data()
    #fetchDataAndUpdate(124)
    #fetch_interval_data()
    time.sleep(300)

