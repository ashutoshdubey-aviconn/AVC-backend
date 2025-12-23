import requests
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')
django.setup()
from wareApp.models import *
from datetime import datetime, timedelta
def update_database(s : Site, data: dict, isRoadcaste: bool):
    if(isRoadcaste):
        roadcaste_obj = DgFuelConsumptionData.objects.create(
            site = s,
            fuel_consumption= 0 if data.get('fuel') == '' else int(data.get('fuel')),
            vehicle_number=data.get('deviceImei'),
            created = datetime.now(),
            epoch_time = int(datetime.now().timestamp()) * 1000
        )
        if(roadcaste_obj):
            return roadcaste_obj, True
        return None, False

    else:
        LoconavObj = DgFuelConsumptionData.objects.create(
            site = s,
            fuel_consumption= 0 if data.get('fuel_capacity') == '' else int(data.get('fuel_capacity')),
            vehicle_number= data.get('vehicle_number'),
            created = datetime.now(),
            epoch_time = data.get('timestamp')
        )
        if(LoconavObj):
            return LoconavObj, True
        return None, False

def get_fuel_data_roadcaste():
    try:
        print("inside")
        url = 'https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234'
        response = requests.get(url)
        data = response.json()
        data = data["data"]
        for i in data:
            s = Site.objects.get(partner_dg_fuel_id = i['deviceImei'])
            r, status = update_database(s, i, True)
            if status:
                print(f'created a fuel entry for site {s.site_name} having a fuel level of {r.fuel_consumption}')
    except Exception as error:
        print(str(error))
    

def get_fuel_data_loconav():
    HEADERS = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    try:
        sites = Site.objects.filter(dg_fuel_system_installed=True)
        for site in sites:
            v = site['partner_dg_fuel_id']
            start_time, end_time = datetime.now().timestamp() - 50, datetime.now().timestamp() 
            if v:
                url = f'https://marketplace.loconav.com/api/v1/vehicles/fuel/current_levels?start_time={start_time}&end_time={end_time}&vehicle_number={v}'
                res = requests.get(url, headers=HEADERS).json()
                data = res["data"]
                if(data):
                    r , status= update_database(site, data[0], False)
                    if(status):
                        print(f'created a fuel entry for site {site.site_name} having a fuel level of {r.fuel_consumption}')
                else:
                    print("Got no response!! perhaps the API failed")
                ...
            else:
                print(f'Fuel Identifier for site {site.site_name} does not exist')
            ... 

    except Exception as error:
        print(str(error))


def main():
    get_fuel_data_roadcaste()
    get_fuel_data_loconav()
    ...

main()
