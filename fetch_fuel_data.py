import time
import os
import json
from datetime import datetime, timedelta
import sys
from warehouse import settings

package_path = os.path.join("..", "django_project")
sys.path.append(package_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()
import psycopg2
import logging
import requests
from wareApp.models import *
from wareApp.fuel_providers import (
    detect_refuel_from_alerts,
    detect_theft_from_alerts,
    fetch_loconav_fuel,
    fetch_roadcast_fuel,
)


def request_json(url, headers=None, params=None, retries=2, timeout=10):
    """Perform a GET and return (json_obj_or_None, raw_text, status_code).
    Retries a couple times on network errors."""
    attempt = 0
    while attempt <= retries:
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            status = r.status_code
            try:
                j = r.json()
            except Exception:
                return None, r.text, status
            return j, r.text, status
        except Exception as err:
            attempt += 1
            if attempt > retries:
                return None, str(err), None
            time.sleep(0.5)


def epoch_ms_from_value(v):
    """Normalize timestamp values (ms vs seconds) to millisecond string.
    Accepts ints/strings. Returns string or None."""
    if v is None:
        return None
    try:
        iv = int(v)
    except Exception:
        return None
    # heuristics: if value looks like ms (>=1e12) keep / ensure ms
    if iv > 1_000_000_000_000:
        return str(iv)
    # if value looks like seconds, convert to ms
    if iv > 1_000_000_000:
        return str(iv * 1000)
    # small number: seconds
    return str(iv * 1000)


def vehicle_variants(v):
    if not v:
        return []
    v = str(v).strip()
    variants = [v]
    try:
        fuel_data_source = ("loconav",)
        variants.append(v.upper())
        variants.append(v.lower())
        variants.append(v.replace(" ", ""))
        alnum = "".join(ch for ch in v if ch.isalnum())
        if alnum not in variants:
            variants.append(alnum)
    except Exception:
        pass
    # dedupe while preserving order
    seen = set()
    out = []
    for x in variants:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def try_loconav_current_levels(vehicle, headers):
    """Try current_levels with variants and fall back to interval_data. Returns (js, raw, used_variant) or (None, raw, None)."""
    now = datetime.now()
    start = int((now - timedelta(hours=24)).timestamp())
    end = int(now.timestamp())
    # try current_levels variants
    for v in vehicle_variants(vehicle):
        url = f"https://marketplace.loconav.sensorise.net/api/v1/vehicles/fuel/current_levels?vehicle_number={v}"
        js, raw, status = request_json(url, headers=headers)
        if js is not None and isinstance(js, dict) and js.get("status"):
            return js, raw, v
        # if API returns 'data' list despite status False, accept it
        if js is not None and isinstance(js, dict) and "data" in js and js["data"]:
            return js, raw, v
    # fallback: try interval_data variants
    for v in vehicle_variants(vehicle):
        url = f"https://marketplace.loconav.com/api/v1/vehicles/fuel/interval_data?start_time={start}&end_time={end}&interval=5&vehicle_number={v}"
        js, raw, status = request_json(url, headers=headers)
        if js is not None and isinstance(js, dict) and "data" in js and js["data"]:
            return js, raw, v
    # log raw to file for debugging
    try:
        os.makedirs("logs/third_party", exist_ok=True)
        fn = f"logs/third_party/loconav_{vehicle}_{int(time.time())}.log"
        with open(fn, "w") as f:
            f.write(raw if raw else str(js))
    except Exception:
        pass
    return None, raw, None


# from wareApp.sendmail import send_mail_for_dg_fuel_under_level


def get_fuel_data_roadcaste():
    try:
        url = "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234"
        response = requests.get(url)
        data = response.json()
        for i in data.get("data"):
            print(i.get("deviceImei"))
            s = Site.objects.filter(partner_dg_fuel_id=i.get("deviceImei"))
            if not s:
                print("No Site Found")
                continue
            now = datetime.now()
            try:
                from wareApp.dg_ingest import ingest_fuel_row

                ingest_fuel_row(
                    site=s[0],
                    vehicle_number=i.get("deviceImei"),
                    epoch_ms=str(int(now.timestamp()) * 1000),
                    fuel_liters=0 if i.get("fuel") == "" else int(i.get("fuel")),
                    source="roadcast",
                    created=now,
                )
            except Exception:
                DgFuelConsumptionData.objects.create(
                    site=s[0],
                    fuel_consumption=0 if i.get("fuel") == "" else int(i.get("fuel")),
                    vehicle_number=i.get("deviceImei"),
                    created=now,
                    epoch_time=str(int(now.timestamp()) * 1000),
                    fuel_data_source="roadcast",
                )
    except Exception as e:
        print(str(e))


def fetchDataFromRoadcasteApi():
    headers = {
        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3bHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.Fwn08jciwxlm659ZYEfq1LpQBAf2fddUZ9zrjmrzcmU"
    }
    data = requests.get(
        "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234",
        # headers = headers
    )
    try:
        data = data.json()
        if data:
            return data["data"][0]["fuel"], data["data"][0]["lastUpdate"]
    except:
        data = data.text
        print("got a response : ", data)
        print("failed to fetch data for {datetime.now}")


def checkRefuel():
    headers = {
        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3Mjg2Mjk0NjIsIm5iZiI6MTcyODYyOTQ2MiwianRpIjoiZjUxYjMyMGItZWM0OC00ZWQwLWIyZWMtM2JhNWRlYjcwMGU2IiwiZXhwIjoxNzI4ODg4NjYyLCJpZGVudGl0eSI6eyJpZCI6Nzg0NDYsImRiIjowLCJjbyI6MSwibmFtZSI6IkF2aWNvbm4iLCJ0eXBlIjoiYWRtaW4iLCJyZWFkX29ubHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.4eju9Peyaid-ZXOfrOT1pVUZV_Hi-ydRu68rVmRbiS4"
    }

    data = requests.get(
        "https://api-track-py.roadcast.co.in/api/v1/auth/dashboard/fuel/last_filled/sensor?device_id=281311&selectedUserId=78446",
        headers=headers,
    )
    try:
        data = data.json()
        if data:
            print(data["data"]["quantity_filled"], data["data"]["timestamp"])
            return data["data"]["quantity_filled"], data["data"]["timestamp"]
    except:
        # data = data.text
        print("got a response : ", data)
        print("failed to fetch data for {datetime.now}")
        return None, None


def checkTheft():
    headers = {
        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3Mjg2Mjk0NjIsIm5iZiI6MTcyODYyOTQ2MiwianRpIjoiZjUxYjMyMGItZWM0OC00ZWQwLWIyZWMtM2JhNWRlYjcwMGU2IiwiZXhwIjoxNzI4ODg4NjYyLCJpZGVudGl0eSI6eyJpZCI6Nzg0NDYsImRiIjowLCJjbyI6MSwibmFtZSI6IkF2aWNvbm4iLCJ0eXBlIjoiYWRtaW4iLCJyZWFkX29ubHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.4eju9Peyaid-ZXOfrOT1pVUZV_Hi-ydRu68rVmRbiS4"
    }
    data = requests.get(
        "https://api-track-py.roadcast.co.in/api/v1/auth/alerts_dashboard?selectedUserId=78446",
        headers=headers,
    )
    try:
        if data:
            print(data["data"]["drainage"])
            return data["data"]["drainage"]
        else:
            return None
    except:
        ...


def fetchDataAndUpdate(site_id):
    try:
        site = Site.objects.get(id=site_id)
        fuel_level, level_timestamp = fetchDataFromRoadcasteApi()
        fuel_refill, refill_timestamp = checkRefuel()
        fuel_theft = checkTheft()
        print(fuel_level, level_timestamp)
        print(fuel_refill, refill_timestamp)
        level_timestamp = datetime.strptime(level_timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")
        date, epoch_time = level_timestamp, str(int(datetime.now().timestamp()) * 1000)
        print(epoch_time)
        if fuel_level:
            try:
                from wareApp.dg_ingest import ingest_fuel_row

                ingest_fuel_row(
                    site=site,
                    vehicle_number=281311,
                    epoch_ms=str(epoch_time),
                    fuel_liters=fuel_level,
                    source="roadcast",
                    created=date,
                )
            except Exception:
                DgFuelConsumptionData.objects.get_or_create(
                    site=site,
                    vehicle_number=281311,
                    fuel_consumption=fuel_level,
                    epoch_time=str(epoch_time),
                    fuel_data_source="roadcast",
                    created=date,
                )
        if fuel_refill:
            refill_timestamp = datetime.strptime(
                refill_timestamp, "%Y-%m-%dT%H:%M:%S.%f"
            )
            refuel_date, refuel_epoch_time = refill_timestamp, int(
                refill_timestamp.timestamp()
            )
            DGFuelAlertsData.objects.get_or_create(
                site=site,
                vehicle_number=281311,
                alert_name="refuel",
                epoch_time=str(refuel_epoch_time),
                fuel_consumption=fuel_refill,
                created=refuel_date,
            )

        if fuel_theft:
            theft_timestamp = datetime.now()
            theft_date = theft_timestamp
            theft_epoch_time = int(theft_timestamp.timestamp())
            DGFuelAlertsData.objects.get_or_create(
                site=site,
                vehicle_number=281311,
                alert_name="theft",
                epoch_time=str(theft_epoch_time),
                defaults={
                    "fuel_consumption": fuel_theft,
                    "created": theft_date,
                },
            )
    except Exception as e:
        print(e)


def fetch_interval_data():
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    # compute a default 24h window if not provided
    interval = 5
    site = Site.objects.get(id=76)
    vehicle_number = "DCGenerator-01"
    end_time = int(datetime.now().timestamp())
    start_time = end_time - 24 * 3600
    url = f"https://marketplace.loconav.com/api/v1/vehicles/fuel/interval_data?start_time={start_time}&end_time={end_time}&interval={interval}&vehicle_number={vehicle_number}"
    js, raw, status = request_json(url, headers=headers)
    if js is None:
        print("interval_data: failed to fetch or parse JSON:", raw)
        return
    print("interval_data raw:", raw)
    if "data" not in js:
        print("interval_data: unexpected response shape, missing 'data':", js)
        return
    for i in js["data"]:
        epoch_value = i.get("time") or i.get("timestamp")
        epoch_ms = epoch_ms_from_value(epoch_value)
        if not epoch_ms:
            continue
        ts = int(int(epoch_ms) / 1000)
        date = datetime.fromtimestamp(ts)
        check_exist_data = DgFuelConsumptionData.objects.filter(
            site=site, vehicle_number=vehicle_number, epoch_time=str(epoch_ms)
        )
        if not check_exist_data.exists():
            try:
                from wareApp.dg_ingest import ingest_fuel_row

                ingest_fuel_row(
                    site=site,
                    vehicle_number=vehicle_number,
                    epoch_ms=epoch_ms,
                    fuel_liters=i.get("value") or i.get("fuel_in_liters"),
                    source="loconav",
                    created=date,
                )
            except Exception:
                DgFuelConsumptionData.objects.create(
                    site=site,
                    vehicle_number=vehicle_number,
                    fuel_consumption=i.get("value") or i.get("fuel_in_liters"),
                    epoch_time=str(epoch_ms),
                    fuel_data_source="loconav",
                    created=date,
                )


def fetch_real_time_data():
    print(
        "############## api call starts at {} ###################3".format(
            datetime.now()
        )
    )
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    site_ids = Site.objects.filter(dg_fuel_system_installed=True)
    alert_api_url = []
    if site_ids.exists():
        for site in site_ids:
            vehicle_number = site.partner_dg_fuel_id
            print("vehicle_number", vehicle_number)
            if vehicle_number:
                print(
                    f"Fetching data for Site ID {site} and Vehicle Number {vehicle_number}"
                )

                try:
                    # Fuel level data API call
                    start_time = datetime.now() - timedelta(hours=23)
                    start_time = int(start_time.timestamp())
                    print("start_time : ", start_time)
                    end_time = int(datetime.now().timestamp())
                    print("end_time :", end_time)
                    url = f"https://marketplace.loconav.sensorise.net/api/v1/vehicles/fuel/current_levels?vehicle_number={vehicle_number}"
                    js, raw, status = request_json(url, headers=headers)
                    if js is None:
                        print(f"current_levels: failed for {vehicle_number}: ", raw)
                        continue
                    if "data" not in js:
                        print(
                            f"current_levels: unexpected shape for {vehicle_number}:",
                            js,
                        )
                        continue
                    data = js["data"]
                    alert_api_url = data
                    print("data", data)

                    if len(data):
                        for i in data:
                            # check_already_exists = DgFuelConsumptionData.objects.filter(site=site,
                            #                                                             vehicle_number=vehicle_number,
                            #                                                             epoch_time=datetime.now().timestamp()*1000)

                            # if not check_already_exists.exists():
                            # prefer API-provided timestamp when present
                            epoch_value = None
                            if isinstance(i, dict):
                                epoch_value = i.get("timestamp") or i.get("time")
                            epoch_ms = epoch_ms_from_value(epoch_value) or str(
                                int(datetime.now().timestamp() * 1000)
                            )
                            # avoid duplicate entries for same epoch
                            exists = DgFuelConsumptionData.objects.filter(
                                site=site,
                                vehicle_number=vehicle_number,
                                epoch_time=str(epoch_ms),
                            )
                            if not exists.exists():
                                date = datetime.fromtimestamp(int(int(epoch_ms) / 1000))
                                DgFuelConsumptionData.objects.create(
                                    site=site,
                                    vehicle_number=vehicle_number,
                                    fuel_consumption=i.get("fuel_in_liters"),
                                    epoch_time=str(epoch_ms),
                                    fuel_data_source="loconav",
                                    created=date,
                                )
                            try:
                                print("###: ", site.dg_fuel_minimum_level)
                                if (
                                    site.dg_fuel_minimum_level
                                    and i["fuel_in_liters"] < site.dg_fuel_minimum_level
                                ):
                                    print("$$$$$")
                                    check_alarm = NewAlarmsNotifications.objects.filter(
                                        site_id=site,
                                        alarm_type=4,
                                        created__gte=datetime.now()
                                        - timedelta(hours=23),
                                    )
                                    print("check_alarm: ", check_alarm)
                                    if not check_alarm.exists():
                                        print("generating alarms")
                                        fuel_level = (
                                            site.dg_fuel_minimum_level
                                            / site.dg_fuel_tank_capacity
                                        ) * 100
                                        NewAlarmsNotifications.objects.create(
                                            site_id=site,
                                            alarm_type=4,
                                            alarm_priority=0,
                                            created=datetime.now(),
                                            fuel_level=fuel_level,
                                        )
                                        data = {
                                            "site_id": site.id,
                                            "vehicle_number": site.partner_dg_fuel_id,
                                            "fuel_level": fuel_level,
                                            "tank_capacity": site.dg_fuel_tank_capacity,
                                        }
                                        # send_mail_for_dg_fuel_under_level(data)
                                        print("mail sent for fuel level")
                            except Exception as err:
                                print(
                                    "Error while generating alarms or sending mail", err
                                )
                            print("Fuel data inserted successfully")
                            # else:
                            #     print("Fuel data entry already exists")
                    else:
                        print("No fuel data from API")
                except Exception as err:
                    print(
                        f"Error while fetching fuel level data for Vehicle {vehicle_number} at Site {site}: {err} at {datetime.now()}"
                    )

                try:
                    # Alerts data API call
                    start_time = datetime.now() - timedelta(hours=23)
                    start_time = int(start_time.timestamp())
                    end_time = int(datetime.now().timestamp())
                    # if  len(alert_api_url) == 0:
                    url_alerts = f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={start_time}&end_time={end_time}"
                    js2, raw2, status2 = request_json(url_alerts, headers=headers)
                    if js2 is None:
                        print(f"alerts API failed for {vehicle_number}:", raw2)
                        continue
                    if "data" not in js2:
                        print(f"alerts API unexpected shape for {vehicle_number}:", js2)
                        continue
                    alert_api_url = js2["data"]
                    # Use detection helpers to normalize alert structures
                    refuel_alerts = detect_refuel_from_alerts(alert_api_url)
                    theft_alerts = detect_theft_from_alerts(alert_api_url)
                    for a in refuel_alerts:
                        ts = a.get("timestamp")
                        if not ts:
                            continue
                        epoch_str = str(int(ts))
                        exists = DGFuelAlertsData.objects.filter(
                            site=site,
                            vehicle_number=vehicle_number,
                            alert_name="refuel",
                            epoch_time=epoch_str,
                        )
                        if not exists.exists():
                            date = datetime.fromtimestamp(int(ts))
                            DGFuelAlertsData.objects.create(
                                site=site,
                                vehicle_number=vehicle_number,
                                alert_name="refuel",
                                epoch_time=epoch_str,
                                fuel_consumption=a.get("value"),
                                created=date,
                            )
                    for a in theft_alerts:
                        ts = a.get("timestamp")
                        if not ts:
                            continue
                        epoch_str = str(int(ts))
                        exists = DGFuelAlertsData.objects.filter(
                            site=site,
                            vehicle_number=vehicle_number,
                            alert_name="theft",
                            epoch_time=epoch_str,
                        )
                        if not exists.exists():
                            date = datetime.fromtimestamp(int(ts))
                            DGFuelAlertsData.objects.create(
                                site=site,
                                vehicle_number=vehicle_number,
                                alert_name="theft",
                                fuel_consumption=a.get("value"),
                                epoch_time=epoch_str,
                                created=date,
                            )
                except Exception as err:
                    print(
                        f"Exception in alert data API for Vehicle {vehicle_number} at Site {site}: {err} at {datetime.now()}"
                    )
            else:
                print("Vehicle number not added for this site : ", site.id)
    print("*************** API finished at {} **************".format(datetime.now()))


def fetch_alerts_data():
    try:
        headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
        vehicle_number = "DCGenerator-01"
        site = Site.objects.get(id=76)
        end_time = int(datetime.now().timestamp())
        start_time = end_time - 24 * 3600
        alert_api_url = requests.get(
            f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={start_time}&end_time={end_time}",
            headers=headers,
        ).json()["data"]
        # print(alert_api_url)
        if "alerts" in alert_api_url:
            print("##################3")
            refuel_alerts = alert_api_url["alerts"]["REFUELING_ALERT"]
            # print(refuel_alerts)
            theft_alerts = alert_api_url["alerts"]["POSSIBLE_FUEL_THEFT_ALERT"]
            for i in refuel_alerts:
                ts = int(i.get("timestamp"))
                epoch_str = str(ts)
                check_refuel_alert_exists = DGFuelAlertsData.objects.filter(
                    site=site,
                    vehicle_number=vehicle_number,
                    alert_name="refuel",
                    epoch_time=epoch_str,
                )
                if not check_refuel_alert_exists.exists():
                    date = datetime.fromtimestamp(ts)
                    DGFuelAlertsData.objects.create(
                        site=site,
                        vehicle_number=vehicle_number,
                        alert_name="refuel",
                        epoch_time=epoch_str,
                        fuel_consumption=i.get("value"),
                        created=date,
                    )
                    print("refuel alert inserted successfully")
            for j in theft_alerts:
                ts = int(j.get("timestamp"))
                epoch_str = str(ts)
                check_theft_alert_exists = DGFuelAlertsData.objects.filter(
                    site=site,
                    vehicle_number=vehicle_number,
                    alert_name="theft",
                    epoch_time=epoch_str,
                )
                if not check_theft_alert_exists.exists():
                    date = datetime.fromtimestamp(ts)
                    DGFuelAlertsData.objects.create(
                        site=site,
                        vehicle_number=vehicle_number,
                        alert_name="theft",
                        fuel_consumption=j.get("value"),
                        epoch_time=epoch_str,
                        created=date,
                    )
                    print("theft alert inserted successfully")
    except Exception as err:
        print("Exception in alert data api  : ", err, " at: ", datetime.now())


def update_dg_fuel_consumption_data():
    print("function start for updating fuel level")
    site_ids = Site.objects.filter(dg_fuel_system_installed=True)
    alert_api_url = []
    if site_ids.exists():
        for site in site_ids:
            vehicle_number = site.partner_dg_fuel_id
            dg_data = DgUnitConsumption.objects.filter(site=site, fetch_fuel_data=True)
            if dg_data.exists():
                for i in dg_data:
                    try:
                        val = fetch_loconav_fuel(
                            vehicle_number, i.dg_start_date, i.dg_end_date
                        )
                        if val is not None:
                            i.dg_fuel_consumption = float(val)
                            print("dg_fuel_consumption: ", datetime.now(), val)
                            i.fetch_fuel_data = False
                            i.save()
                    except Exception as err:
                        print(err)


# fetch_alerts_data()
# fetch_interval_data()

if __name__ == "__main__":
    import os

    def _run_once():
        print("####")
        get_fuel_data_roadcaste()
        # fetchDataAndUpdate(124)
        fetch_real_time_data()
        update_dg_fuel_consumption_data()
        print("@@@")

    if os.environ.get("RUN_ONCE"):
        _run_once()
    else:
        while True:
            _run_once()
            time.sleep(300)
