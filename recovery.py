import time
import os
import json
from datetime import datetime, timedelta
import time
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
import psycopg2
import sys
import logging
import requests
from wareApp.models import *
from wareApp.sendmail import send_mail_for_dg_fuel_under_level


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
    site_ids = Site.objects.filter(dg_fuel_system_installed=True, partner_dg_fuel_id="PBDN450")
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
                        f"https://marketplace.loconav.com/api/v1/vehicles/fuel/current_levels?start_time={start_time}&end_time={end_time}&vehicle_number={vehicle_number}",
                        headers=headers).json()
                    print("dataa: ", data)
                    data = data["data"]
                    alert_api_url = data
                    #print("data",data)

                    """if len(data):
                        for i in data:
                            check_already_exists = DgFuelConsumptionData.objects.filter(site=site,
                                                                                        vehicle_number=vehicle_number,
                                                                                        epoch_time=i["timestamp"])

                            if not check_already_exists.exists():
                                date = datetime.fromtimestamp(int(i["timestamp"] / 1000))
                                DgFuelConsumptionData.objects.create(site=site, vehicle_number=vehicle_number,
                                                                     fuel_consumption=i["fuel_in_liters"],
                                                                     epoch_time=i["timestamp"], created=date)
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
                        print("No fuel data from API")"""
                except Exception as err:
                    print(
                        f"Error while fetching fuel level data for Vehicle {vehicle_number} at Site {site}: {err} at {datetime.now()}")

                try:
                    # Alerts data API call
                    print("alert data")
                    start_time = datetime.now() - timedelta(hours=23)
                    start_time = int(start_time.timestamp())
                    end_time = int(datetime.now().timestamp())
                    if  len(alert_api_url) == 0:
                        alert_api_url = requests.get(
                            f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={start_time}&end_time={end_time}",
                            headers=headers).json()['data']
                    print("check", vehicle_number)
                    print("@@@:", alert_api_url)

                    if 'alerts' in alert_api_url:
                        print("inside")
                        refuel_alerts = alert_api_url['alerts']["REFUELING_ALERT"]
                        theft_alerts = alert_api_url['alerts']['POSSIBLE_FUEL_THEFT_ALERT']
                        print("refuel: ", refuel_alerts)

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


# fetch_alerts_data()
# fetch_interval_data()

while True:
    fetch_real_time_data()
    #fetch_interval_data()
    time.sleep(300)

