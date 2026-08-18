import paho.mqtt.client as mqtt
import re
import requests
import math
from celery import Celery
from wareApp.models import *
from datetime import datetime, timedelta, timezone
from datetime import datetime
from warehouse import settings
from django.core.mail import EmailMessage, send_mail, EmailMultiAlternatives
from django.utils import timezone
from wareApp.sendmail import *
from wareApp.fuel_providers import fetch_loconav_fuel, fetch_roadcast_fuel

app = Celery("warehouse", broker="amqp://guest@localhost//")


def roadcasteAPI(start_time, end_time):
    start_dt_object, end_dt_object = datetime.fromtimestamp(
        start_time
    ), datetime.fromtimestamp(end_time)
    start_time, end_time = (
        start_dt_object.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        end_dt_object.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    )

    url = f"https://api-track-py.roadcast.co.in/api/v1/auth/reports/fuel?start={start_time}&end={end_time}&timezone_offset=-330&variation=0&driver_ids=281311&selected_date={end_time}&device_ids=281311&selectedUserId=78446"

    payload = {}
    headers = {
        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3MjczMzE2MjIsIm5iZiI6MTcyNzMzMTYyMiwianRpIjoiZGMwODI2YzUtYjA3NS00MDg2LWIyNjUtZGM5ZDI3NWEzYjE4IiwiZXhwIjoxNzI3NTkwODIyLCJpZGVudGl0eSI6eyJpZCI6Nzg0NDYsImRiIjowLCJjbyI6MSwibmFtZSI6IkF2aWNvbm4iLCJ0eXBlIjoiYWRtaW4iLCJyZWFkX29ubHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.Fwn08jciwxlm659ZYEfq1LpQBAf2fddUZ9zrjmrzcmU"
    }
    try:
        response = requests.request("GET", url, headers=headers, data=payload)
        if response["data"]:
            return response["data"][0]["consumed_fuel"]
    except:
        return None


def roadcasteAPIUpdated(vehical, start_date, end_date):
    try:
        from datetime import datetime as _dt

        def _ensure_dt(x):
            if x is None:
                return _dt.now()
            if isinstance(x, _dt):
                return x
            try:
                return _dt.fromtimestamp(int(x))
            except Exception:
                try:
                    return _dt.combine(x, _dt.min.time())
                except Exception:
                    return _dt.now()

        sdt = _ensure_dt(start_date)
        edt = _ensure_dt(end_date)
        val = fetch_roadcast_fuel(vehical, sdt, edt)
        return val if val is not None else 0
    except Exception:
        return 0


def get_loconav_fuel_data(vehicle_number, dg_start_date, dg_end_date):
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    fetch_fuel = requests.get(
        f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={dg_start_date}&end_time={dg_end_date}",
        headers=headers,
    ).json()
    fuel = 0
    if "data" in fetch_fuel:
        fetch_fuel = fetch_fuel["data"]
        if "fuel_consumption" in fetch_fuel:
            fuel = fetch_fuel["fuel_consumption"]["value"]
    return fuel


def DG_fuel_for_Roadcaste(site_id, aisle_group, new_unit_consumption, entry_time):
    print("for site 124")
    site = Site.objects.get(id=site_id)
    dg_unit = DgUnitConsumption.objects.filter(site=int(site_id))
    if dg_unit.exists():
        print("DgUnitConsumption entries are present for aisle : ", aisle_group[0])
        last_entry = dg_unit.last()
        check_dg_status = last_entry.is_dg_on
        if check_dg_status and aisle_group[0].power_source not in [0, 2]:
            print("DG of site 124 is already running")
            epoch_time = int(entry_time.timestamp() * 1000)
            last_entry.unit_consumption = (
                last_entry.unit_consumption + new_unit_consumption
            )
            last_entry.epoch_time = epoch_time
            last_entry.dg_end_date = entry_time
            last_entry.save()
        elif aisle_group[0].power_source not in [0, 2] and new_unit_consumption > 0:
            print("DG is Still Running on Site 124")
            if last_entry.fetch_fuel_data:
                last_record = DgUnitConsumption.objects.filter(
                    site=int(site_id), is_dg_on=False
                ).last()
                dg_start_date = int(last_record.dg_start_date.timestamp())
                dg_end_date = int(last_record.dg_end_date.timestamp())
                epoch_time = int(entry_time.timestamp() * 1000)
                fetch_fuel = roadcasteAPIUpdated(
                    site.partner_dg_fuel_id, last_record.dg_start_date.date
                )
                if fetch_fuel:
                    last_record.dg_fuel_consumption = fetch_fuel
                    last_record.save()
            from wareApp.dg_ingest import create_dg_unit_consumption

            create_dg_unit_consumption(
                site=site,
                aisle_group=aisle_group,
                unit_consumption=new_unit_consumption,
                created_time=entry_time,
                is_dg_on=True,
            )
        elif aisle_group[0].power_source in [0, 2] and new_unit_consumption > 0:
            print("turning Off the DG for Site 124")
            print(
                "power source: ",
                aisle_group[0].power_source,
                " consumption : ",
                new_unit_consumption,
            )
            print(
                "power source is currently running is mains supply , making dg last entry off"
            )
            last_entry.is_dg_on = False
            last_entry.save()
            last_record = DgUnitConsumption.objects.filter(
                site=int(site_id), is_dg_on=False
            ).last()
            dg_start_date = int(last_record.dg_start_date.timestamp())
            dg_end_date = int(last_record.dg_end_date.timestamp())
            fetch_fuel = roadcasteAPIUpdated(
                site.partner_dg_fuel_id, last_record.dg_start_date.date
            )
            print("fetched fuel data : ", fetch_fuel)
            if fetch_fuel:
                last_record.dg_fuel_consumption = fetch_fuel
                last_record.save()
            else:
                last_record.fetch_fuel_data = True
                last_record.save()


@app.task
def mqtt_client1():
    # app = Celery('mqtt_client', broker='amqp://guest@localhost/')

    # The callback for when the client receives a CONNACK response from the server.
    def on_connect(client, userdata, flags, rc):
        # logMessage(Constants.TRACE_FLAG_INFO, "Connected with result code " + str(rc))
        print("Connected with result code " + str(rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe("/Acclivate/iOmniControl/#")

    def send_mail_for_alarms(site_id, aisle_id, alarm_type):
        from_mail = settings.EMAIL_HOST_USER
        site = Site.objects.get(id=site_id)
        site_name = site.site_name
        customer_name = site.customer.username
        customer_mail = site.customer.email
        aviconn_user_mail = "yash.kumar@aviconn.in"
        date = timezone.now().strftime("%b %d,%Y")
        if alarm_type == 0:  # for sensor by pass
            print("email is sending for sensor by pass alarm")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=0
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "Sensor By Pass Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 1:  # for light damaged
            print("email is sending for light damaged")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=1
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "Light Damaged Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 2:  # for power theft
            print("email is sending for power theft")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=2
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "Power Theft Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True

        elif alarm_type == 3:  # for internet gone
            print("email is sending for internet gone")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=3
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "No Internet Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 4:  # for no meter reading
            print("email is sending for no meter reading alarm")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=4
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "No Meter Reading Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 5:  # for sensor disconnected
            print("email is sending for sensor disconnected.")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=5
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "Sensor Disconnected Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 6:  # for meter disconnected
            print("email is sending for meter disconnected")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=6
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "Meter Disconnected Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 7:  # for high consumption
            print("email is sending for high consumption alarm")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=7
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "High Consumption Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 8:  # for low consumption
            print("email is sending for low consumption alarm")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=8
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "Low Consumption Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True
        elif alarm_type == 9:  # for no dg run
            print("email for sending no dg run alarm.")
            alarm = AlarmNotifications.objects.filter(
                site_id=site_id, aisle_group=aisle_id, Alarm_type=9
            ).order_by("-created_time")[0]
            alarm_name = alarm.get_Alarm_type_display()
            alarm_created_date = datetime.strftime(alarm.created_time, "%Y/%m/%d")
            print("alarm created date time is: ", alarm_created_date)
            email = ""
            subject_mail = "NO DG RUN Alarm"
            html_message = """
            <html>
            <head>
            Dear Customer {} &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {}
            <br><br>
            Thank you for using Aviconn Advance Smart Energy Management (ASEM).<br><br>
            This is a notification mail regarding {} on site {} is created at {}.
            <br>
            <br>
            Sincerely,
            <br><br>
            Aviconn Solution Pvt Ltd
            </head>
            </html>
            """.format(customer_name, date, alarm_name, site_name, alarm_created_date)
            msg = EmailMultiAlternatives(
                subject_mail, email, from_mail, [customer_mail, aviconn_user_mail]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            return True

    def light_faulty_alarm(site_id, aisle_id, sensor_id, consumption, sensor_on_time):
        customer = Site.objects.get(id=site_id).customer
        data = SiteStaticData.objects.filter(
            site_id=site_id, aisle_id=aisle_id, sensor_id=sensor_id
        )[0]
        total_light = data.total_lights
        wattage_of_one_light = data.total_watts
        theoretical_consumption_one_hour = total_light * wattage_of_one_light / 1000
        total_seconds = 3600
        one_second_consumption = theoretical_consumption_one_hour / total_seconds
        sensor_run_time = sensor_on_time
        practical_consumption = one_second_consumption * sensor_run_time
        current_consumption = consumption
        if practical_consumption == current_consumption:
            print("no need to generate alarm")
            result = 0
        else:
            one_light_consumption = 1 * wattage_of_one_light / 1000
            one_light_hourly_consumption = one_light_consumption / total_seconds
            consmp = one_light_hourly_consumption * sensor_on_time
            if (practical_consumption - consmp) > current_consumption:
                print("raise alarm")
                alarm = AlarmNotifications.objects.create(
                    created_by=customer,
                    user_level=4,
                    site_id=site_id,
                    object_type=3,
                    Alarm_type=1,
                    Alarm_priority=1,
                    created_time=datetime.now(),
                )
                print("alarm created: ", alarm)
                send_mail_for_alarms(site_id, aisle_id, 1)
                result = 1
            else:
                print("no need to generate alarm")
                result = 0
        return result

    # def consumption_alarms(site_id, leg_id, current_consumption, baseline_value):
    #   site = Site.objects.get(id=site_id)
    #  customer = site.customer
    # max_threshold_value = site.max_threshold_value
    # min_threshold_value = site.min_threshold_value
    # current_date = datetime.now()
    # if current_consumption > max_threshold_value:
    #   print("raising high consumption alarm")
    #  high_alarm = AlarmNotifications.objects.create(created_by=customer, user_level=4, site_id=site_id,
    #                                                object_type=0,
    #                                               Alarm_type=7, Alarm_priority=1, created_time=current_date)
    # print("high alarm raised: ", high_alarm)
    # send_mail_for_alarms(site_id, leg_id, 7)
    # elif current_consumption < min_threshold_value:
    #   print("raising low consumption alarm")
    #  low_alarm = AlarmNotifications.objects.create(created_by=customer, user_level=4, site_id=site_id,
    #                                               object_type=0,
    #                                              Alarm_type=8, Alarm_priority=1, created_time=current_date)
    # print("low alarm raised: ", low_alarm)
    # send_mail_for_alarms(site_id, leg_id, 8)
    # else:
    #   print("consumption is fine. no alarms generated at this place")
    # return True

    def consumption_alarms(site_id, leg_id, current_consumption):
        site = Site.objects.get(id=site_id)
        customer = site.customer
        max_threshold_value = site.max_threshold_value
        min_threshold_value = site.min_threshold_value

        current_date = datetime.now()
        date = current_date - timedelta(days=7)
        daily = DailySiteReading.objects.filter(
            associated_Site=site_id, leg_id=leg_id, reading_for__gte=date.date()
        )
        unit_consumption = 0.0
        for i in daily:
            unit_consumption += i.unit_consumption
        average_consumption = unit_consumption / 7
        max_consumption = (average_consumption * max_threshold_value) / 100
        min_consumption = (average_consumption * min_threshold_value) / 100
        total_max_consumption = round(average_consumption + max_consumption, 2)
        total_min_consumption = round(average_consumption - min_consumption, 2)
        if current_consumption > total_max_consumption:
            print("high consumption alarm")
            high_alarm = AlarmNotifications.objects.create(
                created_by=customer,
                user_level=4,
                site_id=site_id,
                object_type=0,
                Alarm_type=7,
                Alarm_priority=1,
                created_time=current_date,
            )
            print("high alarm generated: ", high_alarm)
        elif current_consumption < total_min_consumption:
            print("low consumption alarm")
            low_alarm = AlarmNotifications.objects.create(
                created_by=customer,
                user_level=4,
                site_id=site_id,
                object_type=0,
                Alarm_type=8,
                Alarm_priority=1,
                created_time=current_date,
            )
            print("low alarm generated: ", low_alarm)
        else:
            print("consumption is nearly as average of last 7 days")
        return True

    def power_theft(site_id, current_consumption, baseline_value):
        date = datetime.now()
        customer = Site.objects.get(id=site_id).customer
        leg_id = ""
        if current_consumption > baseline_value:
            print("power theft alarm raised")
            alarm = AlarmNotifications.objects.create(
                created_by=customer,
                user_level=4,
                site_id=site_id,
                object_type=0,
                Alarm_type=2,
                Alarm_priority=1,
                created_time=date,
            )
            print("alarm : ", alarm)
            send_mail_for_alarms(site_id, leg_id, 7)
            result = 1
        else:
            result = 0
        return result

    # The callback for when a PUBLISH message is received from the server.
    def on_message(client, userdata, msg):
        print("######################")
        print("Topic: ", msg.topic + "  Message: " + str(msg.payload))
        print("######################")
        message = str(msg.payload)
        print("message_value :", message)
        head = (msg.topic).split("/")
        locationId = head[3]
        gw_id = head[4]
        print(gw_id)
        msg_type = (head[6]).split("_")
        print("msg_type : ", msg_type)
        msg_subtype = head[7]
        print("This is the message type: ", msg_type)
        location_id = int(locationId)
        site = Site.objects.get(id=int(locationId))
        print("Location Id is : ", int(locationId))
        print("Site Name : {}".format(site.site_name))
        if "FIREALARM" in msg_type:
            print("%%%%%%%%%")
            fire_alarm_data = message.split("'")[1].split(",")
            print("fire_alarm_data : ", fire_alarm_data)
            current_date_time = datetime.now()
            user_email = site.customer.email
            aisles = AisleGroup.objects.filter(site=site)
            print("aisles :", aisles)
            if len(fire_alarm_data):
                print("inside fire alarm data ")
                try:
                    meter_number = int(fire_alarm_data[0].split(":")[1])
                    print("meter_number", meter_number)
                    r_volt = float(fire_alarm_data[1].split(":")[1])
                    print("r volt : ", r_volt)
                    y_volt = float(fire_alarm_data[2].split(":")[1])
                    print("y_volt :", y_volt)
                    b_volt = float(fire_alarm_data[3].split(":")[1])
                    print("b_volt :", b_volt)
                    power_status = int(fire_alarm_data[4].split(":")[1])
                    print("motor_status :", power_status)
                    fire_pump_alarm = FirePumpAlarm.objects.filter(
                        Site=site, Meter_Number=meter_number
                    )
                    print("fire_site :", fire_pump_alarm)
                    if fire_pump_alarm.exists():
                        print("inside hydrant pump")
                        initial_r_volt = fire_pump_alarm[0].r_volt
                        print("initial_r_volt", initial_r_volt)
                        initial_y_volt = fire_pump_alarm[0].y_volt
                        print("initial_y_volt", initial_y_volt)
                        initial_b_volt = fire_pump_alarm[0].b_volt
                        print("initial_b_volt", initial_b_volt)
                        initial_motor_status = fire_pump_alarm[0].motor_status
                        fire_pump_alarm.update(
                            r_volt=r_volt,
                            y_volt=y_volt,
                            b_volt=b_volt,
                            motor_status=power_status,
                            Meter_Number=meter_number,
                            Updated_on=datetime.now(),
                        )
                        updated_r_volt = fire_pump_alarm[0].r_volt
                        print("updated_r_volt", updated_r_volt)
                        updated_y_volt = fire_pump_alarm[0].y_volt
                        updated_b_volt = fire_pump_alarm[0].b_volt
                        deviceName = fire_pump_alarm[0].aisleGroup
                        print("devicename:", deviceName)
                        aisleGrpObject = AisleGroup.objects.get(id=deviceName.id)
                        print("aisle grp object ", aisleGrpObject)
                        mail_difference_time = 600
                        if (
                            updated_r_volt > 200
                            and updated_y_volt < 100
                            and updated_b_volt > 200
                            and power_status == 1
                        ):
                            print("motor on in auto mode")
                            alarm_type = "Motor-On in Auto-Mode"
                            check_previous_mail = Email_History.objects.filter(
                                fire_site=site, deviceName=aisleGrpObject, email_for=5
                            ).order_by("-created")
                            if check_previous_mail.exists():
                                print("mail exists")
                                last_mail_time = check_previous_mail[0].created
                                difference = datetime.now() - last_mail_time
                                print("calculating time differnce from previous mail")
                                print("differnce is : ", difference.total_seconds())
                                if difference.total_seconds() > mail_difference_time:
                                    print(
                                        "sending mail, difference is more than 10 minutes"
                                    )
                                    send_email = send_mail_fire_alarm_user(
                                        user_email, alarm_type, deviceName, power_status
                                    )
                                    Email_History.objects.create(
                                        fire_site=site,
                                        deviceName=aisleGrpObject,
                                        email_for=5,
                                        created=datetime.now(),
                                    )
                                else:
                                    print("last mail sent 10 minutes before")
                            else:
                                print(
                                    "sending first mail for motor on condition in auto mode"
                                )
                                send_email = send_mail_fire_alarm_user(
                                    user_email, alarm_type, deviceName, power_status
                                )
                                Email_History.objects.create(
                                    fire_site=site,
                                    deviceName=aisleGrpObject,
                                    email_for=5,
                                    created=datetime.now(),
                                )
                        if (
                            updated_r_volt < 100
                            and updated_y_volt > 200
                            and updated_b_volt > 200
                            and power_status == 1
                        ):
                            print("motor on in manual mode")
                            alarm_type = "Motor-On in Manual-Mode"
                            check_previous_mail = Email_History.objects.filter(
                                fire_site=site, deviceName=aisleGrpObject, email_for=5
                            ).order_by("-created")
                            if check_previous_mail.exists():
                                print("mail exists")
                                last_mail_time = check_previous_mail[0].created
                                difference = datetime.now() - last_mail_time
                                print("calculating time differnce from previous mail")
                                print("differnce is : ", difference.total_seconds())
                                if difference.total_seconds() > mail_difference_time:
                                    print(
                                        "sending mail, difference is more than 10 minutes"
                                    )
                                    send_email = send_mail_fire_alarm_user(
                                        user_email, alarm_type, deviceName, power_status
                                    )
                                    Email_History.objects.create(
                                        fire_site=site,
                                        deviceName=aisleGrpObject,
                                        email_for=5,
                                        created=datetime.now(),
                                    )
                                else:
                                    print("last mail sent 10 minutes before")
                            else:
                                print(
                                    "sending first mail for motor on condition in manual mode"
                                )
                                send_email = send_mail_fire_alarm_user(
                                    user_email, alarm_type, deviceName, power_status
                                )
                                Email_History.objects.create(
                                    fire_site=site,
                                    deviceName=aisleGrpObject,
                                    email_for=5,
                                    created=datetime.now(),
                                )
                        if (
                            updated_r_volt > 200
                            and updated_y_volt < 100
                            and updated_b_volt > 200
                            and initial_r_volt < 100
                            and initial_y_volt > 200
                            and initial_b_volt > 200
                        ):
                            print("manual-mode to auto-mode")
                            alarm_type = "Manual-Mode to Auto-Mode"
                            send_email = send_mail_fire_alarm_user(
                                user_email, alarm_type, deviceName, power_status
                            )
                            Email_History.objects.create(
                                fire_site=site,
                                deviceName=aisleGrpObject,
                                email_for=2,
                                created=datetime.now(),
                            )

                        elif (
                            initial_r_volt > 200
                            and initial_y_volt < 100
                            and initial_b_volt > 200
                            and updated_r_volt < 100
                            and updated_y_volt > 200
                            and updated_b_volt > 200
                        ):
                            print("auto mode to manual mode")
                            alarm_type = "Auto-Mode to Manual-Mode"
                            send_email = send_mail_fire_alarm_user(
                                user_email, alarm_type, deviceName, power_status
                            )
                            print("send_email", send_email)
                            Email_History.objects.create(
                                fire_site=site,
                                deviceName=aisleGrpObject,
                                email_for=1,
                                created=datetime.now(),
                            )

                        elif (
                            initial_r_volt > 200
                            and initial_y_volt < 100
                            and initial_b_volt > 200
                            and updated_r_volt < 100
                            and updated_y_volt < 100
                            and updated_b_volt > 200
                        ):
                            print("auto to off")
                            alarm_type = "Auto-Mode to Off-Mode"
                            send_email = send_mail_fire_alarm_user(
                                user_email, alarm_type, deviceName, power_status
                            )
                            Email_History.objects.create(
                                fire_site=site,
                                deviceName=aisleGrpObject,
                                email_for=4,
                                created=datetime.now(),
                            )
                        elif (
                            initial_r_volt < 100
                            and initial_y_volt < 100
                            and initial_b_volt > 200
                            and updated_r_volt < 100
                            and updated_y_volt < 100
                            and updated_b_volt > 200
                        ):
                            print("manual to off")
                            alarm_type = "Manual-Mode to Off-Mode"
                            send_email = send_mail_fire_alarm_user(
                                user_email, alarm_type, deviceName, power_status
                            )
                            Email_History.objects.create(
                                fire_site=site,
                                deviceName=aisleGrpObject,
                                email_for=4,
                                created=datetime.now(),
                            )
                        elif (
                            initial_r_volt < 100
                            and initial_y_volt < 100
                            and initial_b_volt > 200
                            and updated_r_volt > 200
                            and updated_y_volt < 100
                            and updated_b_volt > 200
                        ):
                            print("off to auto")
                            alarm_type = "Off-Mode to Auto-Mode"
                            send_email = send_mail_fire_alarm_user(
                                user_email, alarm_type, deviceName, power_status
                            )
                            Email_History.objects.create(
                                fire_site=site,
                                deviceName=aisleGrpObject,
                                email_for=2,
                                created=datetime.now(),
                            )
                        elif (
                            initial_r_volt < 100
                            and initial_y_volt < 100
                            and initial_b_volt > 200
                            and updated_r_volt < 100
                            and updated_y_volt > 200
                            and updated_b_volt > 200
                        ):
                            print("off to manual")
                            alarm_type = "Off-Mode to Manual-Mode"
                            send_email = send_mail_fire_alarm_user(
                                user_email, alarm_type, deviceName, power_status
                            )
                            Email_History.objects.create(
                                fire_site=site,
                                deviceName=aisleGrpObject,
                                email_for=1,
                                created=datetime.now(),
                            )
                        else:
                            print("No conditions matched")
                    else:
                        pass
                except Exception as err:
                    print("Eror in fire alarm : ", err)
        if "consumption" in msg_type:
            try:
                print("These are the values")
                # Balance, Reading, Cost, Cummulative_units, Time, Site_cummulative, Room_id, rc= re.search(r'Bal :(.*), Reading :(.*), Cost :(.*), cumulative_units :(.*), Current_time :(.*)',
                # r'total_property_cumulative :(.*), room_id :(.*),Rc :(.*)',message).group()
                data = message.split(",")
                consumption_time = str(data[0])
                consumption = str(data[1])
                time = data[3]
                print("time: ", time)
                saving = str(data[2])
                leg_Meter_Reading = str(data[4].split(":")[1])
                current_hour_total_consumption = str(data[5])
                aisle_group = str(data[6])
                gw_total_cumulative = str(data[7])
                pervious_hour_total_consumption = str(data[8])
                gw_total_cumulative_units = float(gw_total_cumulative.split(":")[1])
                leg_name = str(leg_Meter_Reading.split("_")[0])
                # meter_reading= float()***************************
                current_hour_gw_unit_consumption = float(
                    current_hour_total_consumption.split(":")[1]
                )
                previous_hour_gw_unit_consumption = float(
                    pervious_hour_total_consumption.split(":")[1]
                )
                consuption_time_in_sec = float((consumption_time.split(":"))[1])
                new_unit_consumption = float((consumption.split(":"))[1])
                aisle_group_id = int((aisle_group.split(":"))[1])
                message_time = (time.split(":"))[1].split(" ")
                print("Message hour :", message_time[1])
                print(
                    "Consumption_time_in_secs = {}, New_unit_consumption = {}, Aisle_group_id = {}, Date = {}".format(
                        consuption_time_in_sec,
                        new_unit_consumption,
                        aisle_group_id,
                        message_time[0],
                    )
                )
                date = datetime.strptime(message_time[0], "%Y-%m-%d")
                dateHourLowerLimitCheck = date.replace(
                    hour=int(message_time[1]), minute=0, second=0, microsecond=0
                )
                dateHourUpperLimitCheck = date.replace(
                    hour=int(message_time[1]), minute=59, second=59, microsecond=0
                )
                print(dateHourLowerLimitCheck)
                print(dateHourUpperLimitCheck)
                aisle_entry = HourlySiteReading.objects.filter(
                    associated_Site=int(location_id), leg_id=aisle_group_id
                )
                hourly_entry = aisle_entry.filter(
                    reading_from__gte=dateHourLowerLimitCheck,
                    reading_from__lte=dateHourUpperLimitCheck,
                )
                daily_entry = DailySiteReading.objects.filter(
                    associated_Site=int(location_id),
                    leg_id=aisle_group_id,
                    reading_for=date.date(),
                )
                print("Now checking condition for entry or update in hourly reading.")
                aisle_group = AisleGroup.objects.filter(
                    site=site, attached_leg_id=str(aisle_group_id)
                )
                # DgUnitConsumption logic starts here only for wh metering

                if site.site_type == 1 and site.dg_fuel_system_installed:
                    try:
                        print("message time : ", message_time)
                        msg_time = time.split(":")[1:]
                        msg_time = ":".join(msg_time)
                        print("msg time: ", msg_time)
                        try:
                            entry_time = datetime.strptime(
                                msg_time, "%Y-%m-%d %H:%M:%S.%f"
                            )
                        except:
                            entry_time = datetime.strptime(
                                msg_time, "%Y-%m-%d %H:%M:%S"
                            )
                        print("entry time: ", entry_time)
                        # filter by the actual message date rather than a hard-coded date
                        dg_unit = DgUnitConsumption.objects.filter(
                            site=int(location_id), created__date=entry_time.date()
                        )
                        if dg_unit.exists():
                            print(
                                "DgUnitConsumption entries are present for aisle : ",
                                aisle_group_id,
                            )
                            last_entry = dg_unit.last()
                            check_dg_status = last_entry.is_dg_on
                            # provider selection: prefer explicit `partner_dg_provider`, fall back to numeric heuristic
                            provider = (
                                (getattr(site, "partner_dg_provider", None) or "")
                                .strip()
                                .lower()
                            )
                            if not provider:
                                pid = (site.partner_dg_fuel_id or "").strip()
                                provider = "roadcast" if pid.isdigit() else "loconav"
                            if provider == "roadcast":
                                try:
                                    DG_fuel_for_Roadcaste(
                                        location_id,
                                        aisle_group,
                                        new_unit_consumption,
                                        entry_time,
                                    )
                                except Exception as e:
                                    print(
                                        "DG_fuel_for_Roadcaste failed for",
                                        location_id,
                                        "error:",
                                        e,
                                    )

                            if check_dg_status and aisle_group[0].power_source != 0:
                                # entry_time = datetime.strptime(msg_time, "%Y-%m-%d %H:%M:%S.%f")
                                epoch_time = int(entry_time.timestamp() * 1000)
                                print(
                                    "dg is running continously from last entry, updating last entry"
                                )
                                last_entry.unit_consumption = (
                                    last_entry.unit_consumption + new_unit_consumption
                                )
                                last_entry.epoch_time = epoch_time
                                last_entry.dg_end_date = entry_time
                                last_entry.save()
                                try:
                                    print("check for dg overtime run")
                                    if (
                                        (
                                            last_entry.dg_end_date
                                            - last_entry.dg_start_date
                                        ).seconds
                                    ) / 60 > site.dg_overtime:
                                        check_alarm_dg_overtime = (
                                            NewAlarmsNotifications.objects.filter(
                                                site_id=site,
                                                alarm_type=3,
                                                created__gte=datetime.now()
                                                - timedelta(hours=2),
                                            )
                                        )
                                        if not check_alarm_dg_overtime.exists():
                                            NewAlarmsNotifications.objects.filter(
                                                site_id=site,
                                                alarm_type=3,
                                                created=datetime.now(),
                                            )
                                            data = {
                                                "start_time": last_entry.dg_start_date,
                                                "end_time": last_entry.dg_end_date,
                                                "site_id": site.id,
                                            }
                                            send_alarm_for_dg_overtime(data)
                                        print("generating alarm")
                                except Exception as err:
                                    print("Error in checking alarm for dg overtime run")
                                print("data updated")
                            else:
                                if (
                                    aisle_group[0].power_source != 0
                                    and new_unit_consumption > 0
                                ):
                                    print(
                                        "dg status gets off in previous time when data came, creating new entry"
                                    )
                                    # getting fuel consumption of last entry
                                    print(
                                        "fetching fuel consumption of last entry from loconav api"
                                    )
                                    last_record = DgUnitConsumption.objects.filter(
                                        site=int(location_id), is_dg_on=False
                                    ).last()
                                    dg_start_date = int(
                                        last_record.dg_start_date.timestamp()
                                    )
                                    dg_end_date = int(
                                        last_record.dg_end_date.timestamp()
                                    )
                                    if location_id in [124, 118, 140, 153, 156, 169]:
                                        fuel = roadcasteAPIUpdated(
                                            site.partner_dg_fuel_id,
                                            last_record.dg_start_date,
                                            last_record.dg_end_date,
                                        )
                                    else:
                                        fuel = get_loconav_fuel_data(
                                            site.partner_dg_fuel_id,
                                            dg_start_date,
                                            dg_end_date,
                                        )
                                    print("fuel calculated value is: ", fuel)
                                    if fuel:
                                        last_record.dg_fuel_consumption = fuel
                                        last_record.save()
                                        print(
                                            "fuel data updated of litre {} at {}".format(
                                                fuel, datetime.now()
                                            )
                                        )
                                    else:
                                        print("fuel data not updated")
                                        last_record.fetch_fuel_data = True
                                        last_record.save()
                                    # code commented by yash
                                    """headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
                                    vehicle_number = site.partner_dg_fuel_id
                                    fetch_fuel = requests.get(f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={dg_start_date}&end_time={dg_end_date}", headers=headers).json()
                                    print("fetched fuel data : ", fetch_fuel)
                                    if 'data' in fetch_fuel:
                                        fetch_fuel = fetch_fuel["data"]
                                        if 'fuel_consumption' in fetch_fuel:
                                            fuel = fetch_fuel['fuel_consumption']['value']
                                            last_record.dg_fuel_consumption = fuel
                                            last_record.save()
                                            print("fuel data updated of litre {} at {}".format(fuel, datetime.now()))
                                    else:
                                        print("fuel data not updated")
                                        last_record.fetch_fuel_data = True
                                        last_record.save()"""

                                    # entry_time = datetime.strptime(message_time[0], "%Y-%m-%d %H:%M:%S")
                                    epoch_time = int(entry_time.timestamp() * 1000)
                                    from wareApp.dg_ingest import (
                                        create_dg_unit_consumption,
                                    )

                                    create_dg_unit_consumption(
                                        site=site,
                                        aisle_group=aisle_group,
                                        unit_consumption=new_unit_consumption,
                                        created_time=entry_time,
                                        is_dg_on=True,
                                    )
                                    print("new dg entry created")
                                else:
                                    if (
                                        aisle_group[0].power_source == 0
                                        and new_unit_consumption > 0
                                    ):
                                        print(
                                            "power source: ",
                                            aisle_group[0].power_source,
                                            " consumption : ",
                                            new_unit_consumption,
                                        )
                                        print(
                                            "power source is currently running is mains supply , making dg last entry off"
                                        )
                                        if last_entry.is_dg_on:
                                            print(
                                                "making dg last entry off at : ",
                                                datetime.now(),
                                            )
                                            last_entry.is_dg_on = False
                                            last_entry.save()
                                            print(
                                                "dg status gets off in previous time when data came, creating new entry"
                                            )
                                            # getting fuel consumption of last entry
                                            print(
                                                "fetching fuel consumption of last entry from loconav api"
                                            )
                                            last_record = (
                                                DgUnitConsumption.objects.filter(
                                                    site=int(location_id),
                                                    is_dg_on=False,
                                                ).last()
                                            )
                                            dg_start_date = int(
                                                last_record.dg_start_date.timestamp()
                                            )
                                            dg_end_date = int(
                                                last_record.dg_end_date.timestamp()
                                            )
                                            if location_id in [
                                                124,
                                                118,
                                                140,
                                                153,
                                                156,
                                                169,
                                            ]:
                                                fuel = roadcasteAPIUpdated(
                                                    site.partner_dg_fuel_id,
                                                    last_record.dg_start_date,
                                                    last_record.dg_end_date,
                                                )
                                            else:
                                                fuel = get_loconav_fuel_data(
                                                    site.partner_dg_fuel_id,
                                                    dg_start_date,
                                                    dg_end_date,
                                                )
                                            if fuel:
                                                last_record.dg_fuel_consumption = fuel
                                                last_record.save()
                                                print(
                                                    "fuel data updated of litre {} at {}".format(
                                                        fuel, datetime.now()
                                                    )
                                                )
                                            else:
                                                print("fuel data not updated")
                                                last_record.fetch_fuel_data = True
                                                last_record.save()

                                            # headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
                                            # vehicle_number = site.partner_dg_fuel_id
                                            # fetch_fuel = requests.get(f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={vehicle_number}&start_time={dg_start_date}&end_time={dg_end_date}", headers=headers).json()
                                            # print("fetched fuel data : ", fetch_fuel)
                                            # if 'data' in fetch_fuel:
                                            #     fetch_fuel = fetch_fuel["data"]
                                            #     if 'fuel_consumption' in fetch_fuel:
                                            #         fuel = fetch_fuel['fuel_consumption']['value']
                                            #         last_record.dg_fuel_consumption = fuel
                                            #         last_record.save()
                                            #         print("fuel data updated of litre {} at {}".format(fuel, datetime.now()))
                                            # else:
                                            #     last_record.fetch_fuel_data = True
                                            #     last_record.save()
                        else:
                            if (
                                aisle_group[0].power_source != 0
                                and new_unit_consumption > 0
                            ):
                                print(
                                    "creating first ever entry for dg with aisle group: ",
                                    aisle_group_id,
                                )
                                # entry_time = datetime.strptime(message_time[0], "%Y-%m-%d %H:%M:%S")
                                epoch_time = int(entry_time.timestamp() * 1000)
                                from wareApp.dg_ingest import create_dg_unit_consumption

                                create_dg_unit_consumption(
                                    site=site,
                                    aisle_group=aisle_group,
                                    unit_consumption=new_unit_consumption,
                                    created_time=entry_time,
                                    is_dg_on=True,
                                )
                    except Exception as err:
                        print(
                            "Exception while storing/updating dg unit consumption data : ",
                            str(err),
                        )

                # DgUnitConsumption logic ends here
                aisle_group_status, aisle_group_active = False, False
                site_baseline, leg_hourly_baseline = 0.0, 0.0
                # for sensor aisle unit consumption
                try:
                    sensor_aisle = aisle_group[0].on_sensor_power
                    if sensor_aisle:
                        print("storing sensor aisle data in sensor aisle table")
                        msg_time = time.split(":")[1:]
                        msg_time = ":".join(msg_time)
                        print("msg time: ", msg_time)
                        entry_time = datetime.strptime(msg_time, "%Y-%m-%d %H:%M:%S.%f")
                        SensorAisleUnitConsumption.objects.create(
                            associated_Site=site,
                            aisle_group=aisle_group[0],
                            leg_id=aisle_group_id,
                            unit_consumption=new_unit_consumption,
                            reading_for=entry_time,
                        )
                        print(
                            "data stored for leg : {} in sensor table".format(
                                aisle_group_id
                            )
                        )
                except Exception as err:
                    print("Error while storing sensor aisle data ", err)
                # ends here
                if aisle_group[0].is_visible:
                    aisle_group_status = True
                if aisle_group[0].is_active:
                    aisle_group_active = True
                if hourly_entry.exists():
                    # new_consumption = hourly_entry[0].unit_consumption + new_unit_consumption
                    hourly_entry.update(
                        unit_consumption=current_hour_gw_unit_consumption
                    )
                    print(
                        "The hourly reading for leg id {} in site {} updated".format(
                            aisle_group_id, site.site_name
                        )
                    )
                else:
                    #####First packet of next hour received##############################
                    # Checking previous hour data entry, for initiating data recovery mechanism in case of data loss.
                    print(
                        "Checking previous hour data entry for aisle group id {} of site {}.".format(
                            aisle_group_id, site.site_name
                        )
                    )
                    dateHourLowerLimitCheck1 = dateHourLowerLimitCheck - timedelta(
                        hours=1
                    )
                    dateHourUpperLimitCheck1 = dateHourUpperLimitCheck - timedelta(
                        hours=1
                    )
                    previous_hour_entry = aisle_entry.filter(
                        reading_from__gte=dateHourLowerLimitCheck1,
                        reading_from__lte=dateHourUpperLimitCheck1,
                    )
                    if previous_hour_entry.exists():
                        print("Checking for any loss in previous hour data.")
                        pervious_hour_server_unit_consumption = previous_hour_entry[
                            0
                        ].unit_consumption
                        if (
                            pervious_hour_server_unit_consumption
                            != previous_hour_gw_unit_consumption
                        ):
                            # for updating any gap in consumption between server's and gateway's hourly consumption.
                            consumption_gap = abs(
                                previous_hour_gw_unit_consumption
                                - pervious_hour_server_unit_consumption
                            )
                            print(
                                "This is the gap in server's last hour total consumption and"
                                " gateway's last hour total consumption : {}".format(
                                    consumption_gap
                                )
                            )
                            print(
                                "Updating the server hourly consumption with gateway hourly consumption."
                            )
                            previous_hour_entry.update(
                                unit_consumption=previous_hour_gw_unit_consumption
                            )
                            print(
                                "Server hourly consumption synced with gateway hourly consumption."
                            )
                            ### note: This will only sync hourly data but not the daily unit consumption ######
                            #### Daily unit consumption sync is done below #######
                        else:
                            print("Previous hour data is synced.")
                        if aisle_group_active:
                            aisle_group_baseline = SiteBaseline.objects.filter(
                                associated_site_id=int(location_id),
                                leg_id=str(aisle_group_id),
                            ).last()
                            leg_hourly_baseline = (
                                aisle_group_baseline.baseline_value
                                / aisle_group_baseline.working_hours
                            )
                            print("Now calculating saving for previous hour.")
                            hourly_saving = (
                                leg_hourly_baseline
                                - previous_hour_entry[0].unit_consumption
                            )
                            previous_hour_entry.update(energy_saved=hourly_saving)
                            print(
                                "Hourly saving of {} in {} of {} hour updated.".format(
                                    previous_hour_entry[0].leg_id,
                                    site.site_name,
                                    dateHourLowerLimitCheck1,
                                )
                            )
                        # Creating new hour entry after receving first packet of new hour  #########
                        print(
                            "Creating new entry in hourly consumption table for aisle group id {} of site {}.".format(
                                aisle_group_id, site.site_name
                            )
                        )
                        #### Sept-2022  now sync the daily unit consumption based on previous hours unit consumptions #####
                        #### This is required when consumption packets send by gateway and not received by cloud ######
                        #### due to this daily unit consumption will be out of sync.############
                        ####### Note: In a running current hour we keep adding delta units consumption in daily unit consumption.##
                        ##### this is done since gateway do not send daily unit consumption data in consumption packets #####
                        ##### komal to add code here. ##########
                        if daily_entry.exists():
                            dateofDailyEntry = daily_entry[0].reading_for
                            dailyUnitConsumption = daily_entry[0].unit_consumption

                            print("dateofDailyEntry : ", dateofDailyEntry)
                            print("daily Unit consumption ", dailyUnitConsumption)
                            if dateofDailyEntry == date.date():
                                ### Now sync of daily consumption based on hourly data till this point

                                oneDayHourlyData = HourlySiteReading.objects.filter(
                                    associated_Site=site,
                                    aisle_group=aisle_group[0],
                                    reading_from__date=date.date(),
                                    reading_to__date=date.date(),
                                )
                                totalConsumptionofAllHours = 0.0
                                for hourlyloop in oneDayHourlyData:
                                    totalConsumptionofAllHours += (
                                        hourlyloop.unit_consumption
                                    )
                                    print(
                                        "Daily consumption as per all hours :",
                                        totalConsumptionofAllHours,
                                    )
                                print(
                                    "Daily entry units before updating is :",
                                    dailyUnitConsumption,
                                )
                                if totalConsumptionofAllHours != dailyUnitConsumption:
                                    ### Now Daily Entry synced with sum of houly Data
                                    print("inside tryy")
                                    daily_entry_instance = daily_entry[0]
                                    daily_entry_instance.unit_consumption = (
                                        totalConsumptionofAllHours
                                    )
                                    daily_entry_instance.save()
                                    print(
                                        "daily unit after update",
                                        daily_entry[0].unit_consumption,
                                    )
                                    print(
                                        "Now daily entry synced with sum of hourly data"
                                    )

                                else:
                                    print(
                                        "Daily and hourly buckets both are already in  synced"
                                    )
                            else:
                                print("Daily entry Date not equal to packet date")
                        else:
                            ### Handling if daily entry doesnot exists.######
                            print(
                                "This is not possible why daily entry doesnot created"
                            )

                        HourlySiteReading.objects.create(
                            associated_Site=site,
                            aisle_group=aisle_group[0],
                            leg_id=aisle_group_id,
                            unit_consumption=new_unit_consumption,
                            hourly_baseline_value=leg_hourly_baseline,
                            reading_from=dateHourLowerLimitCheck,
                            reading_to=dateHourUpperLimitCheck,
                            is_visible=True,
                        )
                        print(
                            "New hourly entry for leg id {} is created.".format(
                                aisle_group_id
                            )
                        )
                    else:
                        if (
                            aisle_entry.count() > 0
                        ):  # If not the first ever entry for this aisle group on this site.
                            print(
                                "No previous hour entry found for this aisle group, data loss suspected."
                            )
                            last_hourly_entry = HourlySiteReading.objects.filter(
                                associated_Site=int(location_id), leg_id=aisle_group_id
                            ).last()
                            print("abhishek's debugging start")
                            print(last_hourly_entry)

                            print(
                                "This is the time for last entry for this aisle group : {}".format(
                                    last_hourly_entry.reading_to
                                )
                            )
                            time_gap = datetime.now() - last_hourly_entry.reading_to
                            print("Reading missed for {}.".format(time_gap))
                            print("Starting recovery mechanism.")
                            print(
                                "Sending command to gateway to sync data for recovery for this aisle group."
                            )
                            topictosend = (
                                "/Acclivate/iOmniControl/"
                                + str(location_id)
                                + "/"
                                + str(gw_id)
                                + "/in/"
                                + "sync/consumption"
                                + "/state"
                            )
                            last_hourly_entry_time = datetime.strftime(
                                last_hourly_entry.reading_to, "%Y-%m-%d %H:%M:%S.%f"
                            )
                            msg = (
                                "Missed_consumption_time_in_secs :"
                                + str(time_gap.total_seconds())
                                + ",Aisle_grp :"
                                + str(aisle_group_id)
                                + ",Last_Synced_hour :"
                                + last_hourly_entry_time
                            )
                            client.publish(topictosend, msg, qos=0, retain=False)
                            print(topictosend)
                            print(msg)
                        else:
                            print(
                                "Creating first ever entry in hourly and daily consumption table for aisle group id {} of site {}.".format(
                                    aisle_group_id, site.site_name
                                )
                            )
                            if aisle_group_active:
                                aisle_group_baseline = SiteBaseline.objects.filter(
                                    associated_site_id=int(location_id),
                                    leg_id=str(aisle_group_id),
                                ).last()
                                leg_hourly_baseline = (
                                    aisle_group_baseline.baseline_value
                                    / aisle_group_baseline.working_hours
                                )
                                site_baseline = aisle_group_baseline.baseline_value
                            HourlySiteReading.objects.create(
                                associated_Site=site,
                                aisle_group=aisle_group[0],
                                leg_id=aisle_group_id,
                                unit_consumption=new_unit_consumption,
                                hourly_baseline_value=leg_hourly_baseline,
                                reading_from=dateHourLowerLimitCheck,
                                reading_to=dateHourUpperLimitCheck,
                                is_visible=True,
                            )

                            DailySiteReading.objects.create(
                                associated_Site=site,
                                aisle_group=aisle_group[0],
                                leg_id=aisle_group_id,
                                unit_consumption=new_unit_consumption,
                                daily_baseline_value=site_baseline,
                                reading_for=date.date(),
                                is_visible=True,
                            )
                            print(
                                "New entries created in hourly and daily consumption table for aisle group id {} of site {}.".format(
                                    aisle_group_id, site.site_name
                                )
                            )
                            return

                print("Now checking condition for entry or update in daily reading.")
                daily_saving, site_baseline = 0.0, 0.0
                if aisle_group_active:
                    today = dateHourLowerLimitCheck.replace(hour=0, microsecond=0)
                    aisle_group_baseline = SiteBaseline.objects.filter(
                        associated_site_id=int(location_id), leg_id=str(aisle_group_id)
                    ).last()
                    site_baseline = aisle_group_baseline.baseline_value
                    for i in aisle_entry.filter(reading_from__gte=today):
                        daily_saving += i.energy_saved
                if daily_entry.exists():
                    print("Updating daily consumption data.")
                    new_consumption = (
                        daily_entry[0].unit_consumption + new_unit_consumption
                    )
                    daily_entry.update(
                        unit_consumption=new_consumption,
                        energy_saved=(site_baseline - new_consumption),
                        daily_baseline_value=site_baseline,
                    )
                    print("The reading for leg id {} is updated".format(aisle_group_id))

                else:
                    print("Creating new daily consumption entry.")
                    # komal to add code for previous day all hours(24) to daily entry
                    s = Site.objects.get(id=int(location_id))
                    DailySiteReading.objects.create(
                        associated_Site=s,
                        aisle_group=aisle_group[0],
                        leg_id=aisle_group_id,
                        unit_consumption=new_unit_consumption,
                        daily_baseline_value=site_baseline,
                        reading_for=date.date(),
                        is_visible=True,
                    )
                    print(
                        "New daily entry for leg id {} is created.".format(
                            aisle_group_id
                        )
                    )
                    print("Checking for high or low consumption in this aisle group.")
                    current_consumption = DailySiteReading.objects.filter(
                        associated_Site=s,
                        leg_id=aisle_group_id,
                        reading_for=(date.date() - timedelta(days=1)),
                    )[0].unit_consumption
                    consumption_alarms(location_id, aisle_group_id, current_consumption)
            except Exception as e:
                print("Exception in consumption calculation block.")
                print("This is the exception : {}".format(e))

        elif "load" in msg_type:
            print("This message is for load parameters for site {}.".format(site))
            try:
                load = message.split(",")
                load_power = float(load[0].split(":")[1])
                print("load power is : ", load_power)
                r_volts = float(load[1].split(":")[1])
                y_volts = float(load[2].split(":")[1])
                b_volts = float(load[3].split(":")[1])
                r_currents = float(load[4].split(":")[1])
                y_currents = float(load[5].split(":")[1])
                b_currents = float(load[6].split(":")[1])
                power_source = str(load[7].split(":")[1])
                status = str(load[8].split(":")[1])
                meter_number = int(load[9].split(":")[1])
                message_time = str(load[10].split(":")[1])
                load_entry = SiteLoadPower.objects.filter(
                    Associated_Site=int(location_id),
                    Supply_Source=power_source,
                    Meter_Number=meter_number,
                )
                if site.show_voltage_alarms and (
                    r_volts > 0 and y_volts > 0 and b_volts > 0
                ):
                    print(
                        "$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$"
                    )
                    r_phase_voltage_threshold_max = site.r_phase_voltage_threshold_max
                    y_phase_voltage_threshold_max = site.y_phase_voltage_threshold_max
                    b_phase_voltage_threshold_max = site.b_phase_voltage_threshold_max
                    r_phase_voltage_threshold_min = site.r_phase_voltage_threshold_min
                    y_phase_voltage_threshold_min = site.y_phase_voltage_threshold_min
                    b_phase_voltage_threshold_min = site.b_phase_voltage_threshold_min
                    print(
                        "creating  enrty for high voltage data",
                        b_phase_voltage_threshold_max,
                        type(b_phase_voltage_threshold_max),
                    )
                    parameter = SiteLoadParameters.objects.create(
                        site_id=site,
                        power_source=power_source,
                        parameter_type=0,
                        r_phase=r_volts,
                        y_phase=y_volts,
                        b_phase=b_volts,
                        meter_number=meter_number,
                        created=datetime.now(),
                    )
                    fetch_last_entries = SiteLoadParameters.objects.filter(
                        site_id=site, power_source=power_source, parameter_type=0
                    ).order_by("-created")
                    print("fetch_last_entries:", fetch_last_entries)
                    if fetch_last_entries.count() > 6:
                        check_high_volt_alarm = True
                        for i in fetch_last_entries[0:5]:
                            print(
                                "r_Phase value for high vlotage:",
                                i.r_phase,
                                i.y_phase,
                                type(i.b_phase),
                            )
                            if (
                                r_phase_voltage_threshold_max < float(i.r_phase)
                                or y_phase_voltage_threshold_max < float(i.y_phase)
                                or b_phase_voltage_threshold_max < float(i.b_phase)
                            ):

                                print(
                                    "@@@@@@@@@@@@@@@@@@@@@ high voltage @@@@@@@@@@@@@@@@@@@"
                                )
                            else:
                                check_high_volt_alarm = False
                                break
                        if check_high_volt_alarm:
                            print("generate alarm for high consumption")
                            alarm = NewAlarmsNotifications.objects.filter(
                                site_id=site,
                                alarm_type=0,
                                power_source=power_source,
                                created__gte=datetime.now() - timedelta(minutes=30),
                            )
                            if not alarm.exists():
                                print("create alarm")
                                NewAlarmsNotifications.objects.create(
                                    site_id=site,
                                    alarm_type=0,
                                    power_source=power_source,
                                    created=datetime.now(),
                                    alarm_priority=0,
                                    r_phase=r_volts,
                                    y_phase=y_volts,
                                    b_phase=b_volts,
                                )
                                data = {
                                    "r_volts": round(r_volts, 2),
                                    "y_volts": round(y_volts, 2),
                                    "b_volts": round(b_volts, 2),
                                    "r_volt_threshold": r_phase_voltage_threshold_max,
                                    "y_volt_threshold": y_phase_voltage_threshold_max,
                                    "b_volt_threshold": b_phase_voltage_threshold_max,
                                    "site_id": site.id,
                                }
                                send_alarm_for_high_voltage(data)
                                print(
                                    "################### send mail for high Voltage###################"
                                )
                    print("creating entry for low voltage data")
                    parameter = SiteLoadParameters.objects.create(
                        site_id=site,
                        power_source=power_source,
                        parameter_type=1,
                        r_phase=r_volts,
                        y_phase=y_volts,
                        b_phase=b_volts,
                        meter_number=meter_number,
                        created=datetime.now(),
                    )
                    fetch_last_entries = SiteLoadParameters.objects.filter(
                        site_id=site, power_source=power_source, parameter_type=1
                    ).order_by("-created")
                    print("fetch_last_entries for low voltage : ", fetch_last_entries)
                    if fetch_last_entries.count() > 6:
                        check_low_volt_alarm = True
                        for i in fetch_last_entries[0:5]:
                            print(
                                "r_Phase value for low vlotage:",
                                i.r_phase,
                                i.y_phase,
                                type(i.b_phase),
                            )
                            if (
                                r_phase_voltage_threshold_min > float(i.r_phase)
                                or y_phase_voltage_threshold_min > float(i.y_phase)
                                or b_phase_voltage_threshold_min > float(i.b_phase)
                            ):
                                print(
                                    "@@@@@@@@@@@@@@@@@@@@@ Low voltage @@@@@@@@@@@@@@@@@@@"
                                )
                            else:
                                check_low_volt_alarm = False
                                break
                        if check_low_volt_alarm:
                            alarm = NewAlarmsNotifications.objects.filter(
                                site_id=site,
                                alarm_type=1,
                                power_source=power_source,
                                created__gte=datetime.now() - timedelta(minutes=30),
                            )
                            if not alarm.exists():
                                print("generate alarm for low consumption")
                                NewAlarmsNotifications.objects.create(
                                    site_id=site,
                                    alarm_type=1,
                                    power_source=power_source,
                                    created=datetime.now(),
                                    alarm_priority=0,
                                    r_phase=r_volts,
                                    y_phase=y_volts,
                                    b_phase=b_volts,
                                )
                                data = {
                                    "r_volts": r_volts,
                                    "y_volts": y_volts,
                                    "b_volts": b_volts,
                                    "r_volt_threshold": r_phase_voltage_threshold_min,
                                    "y_volt_threshold": y_phase_voltage_threshold_min,
                                    "b_volt_threshold": b_phase_voltage_threshold_min,
                                    "site_id": site.id,
                                }
                                send_alarm_for_low_voltage(data)
                print("Now checking condition for entry or update.")
                if load_entry.exists():
                    print("Updating the load parameters.")
                    # for min and max load starts here
                    r_pf = y_pf = b_pf = 0.0
                    min_load = load_entry[0].min_load
                    max_load = load_entry[0].max_load
                    if site.is_pf_visible:
                        if len(load) == 14:
                            r_pf = float(load[11].split(":")[1])
                            print("r_phase: ", r_pf)
                            y_pf = float(load[12].split(":")[1])
                            print("y_phase:", y_pf)
                            print("b_phase:", load[13].split(":")[1][0:-1])
                            b_pf = float(load[13].split(":")[1][0:-1])
                            print(
                                "power factors value for r-phase : {}, y-phase: {}, b-phase: {}".format(
                                    r_pf, y_pf, b_pf
                                )
                            )
                            r_phase_threshold = site.r_phase_pf_threshold
                            y_phase_threshold = site.y_phase_pf_threshold
                            b_phase_threshold = site.b_phase_pf_threshold
                            if status == "ON":
                                try:
                                    print("checking power factor fluctuation")
                                    pf_check = False
                                    pf = PowerFactorData(
                                        site=site,
                                        supply_source=power_source,
                                        meter_number=meter_number,
                                        created=datetime.now(),
                                    )
                                    if r_pf < r_phase_threshold:
                                        print("fluctuation in r phase power factor")
                                        pf.save()
                                        pf.r_phase_pf = r_pf
                                        pf_check = True
                                    if y_pf < y_phase_threshold:
                                        print("fluctuation in y phase power factor")
                                        pf.save()
                                        pf.y_phase_pf = y_pf
                                        pf_check = True
                                    if b_pf < b_phase_threshold:
                                        print("fluctuation in b phase power factor")
                                        pf.save()
                                        pf.b_phase_pf = b_pf
                                        pf_check = True
                                    if pf_check:
                                        print(
                                            "creating entry for pf fluctuation reference to threshold value"
                                        )
                                        pf.save()
                                        pf_data = {
                                            "r_pf": r_pf,
                                            "y_pf": y_pf,
                                            "b_pf": b_pf,
                                            "r_pf_threshold": r_phase_threshold,
                                            "y_pf_threshold": y_phase_threshold,
                                            "b_pf_threshold": b_phase_threshold,
                                            "site_id": site.id,
                                            "power_source": power_source,
                                        }

                                        try:
                                            check_already_alarm = (
                                                NewAlarmsNotifications.objects.filter(
                                                    site_id=site,
                                                    power_source=power_source,
                                                    alarm_type=2,
                                                    created__gte=datetime.now()
                                                    - timedelta(minutes=30),
                                                )
                                            )
                                            if not check_already_alarm.exists():
                                                alarm = NewAlarmsNotifications.objects.create(
                                                    site_id=site,
                                                    power_source=power_source,
                                                    alarm_type=2,
                                                    alarm_priority=1,
                                                    created=datetime.now(),
                                                    r_phase=r_pf,
                                                    y_phase=y_pf,
                                                    b_phase=b_pf,
                                                )
                                                send_mail_for_pf_fluctuation(pf_data)
                                                print(
                                                    "mail send successfully for bad pd for site: ",
                                                    site.site_name,
                                                )
                                        except Exception as err:
                                            print(
                                                "Error in sending mail for bad pf for site : ",
                                                site.site_name,
                                            )
                                except Exception as err:
                                    print(
                                        "Error in power faction fluctuation record creation logic: ",
                                        err,
                                    )

                    load_entry.update(
                        Associated_Site=site,
                        Site_Total_Load=load_power,
                        r_volt=r_volts,
                        y_volt=y_volts,
                        b_volt=b_volts,
                        r_power_factor=r_pf,
                        y_power_factor=y_pf,
                        b_power_factor=b_pf,
                        r_current=r_currents,
                        y_current=y_currents,
                        b_current=b_currents,
                        Status=status,
                        Updated_on=datetime.now(),
                    )

                    print("site load table  parameters updated.")
                else:
                    print(
                        "Creating the first entry for supply {} for site {}.".format(
                            power_source, site
                        )
                    )
                    SiteLoadPower.objects.create(
                        Associated_Site=site,
                        Site_Total_Load=load_power,
                        r_volt=r_volts,
                        y_volt=y_volts,
                        min_load=load_power,
                        max_load=load_power,
                        b_volt=b_volts,
                        r_current=r_currents,
                        y_current=y_currents,
                        b_current=b_currents,
                        Supply_Source=power_source,
                        Meter_Number=meter_number,
                        Status=status,
                        Updated_on=datetime.now(),
                    )
                    print("New entry for load parameters.")
            except Exception as e:
                print("Exception in load calculation block.")
                print("This is the exception : {}".format(e))

                # load graph data code starts from here
        elif "LoadData" in msg_type:
            print("inside load data")
            load_data = message.split("'")[1].split(",")
            print("load data: ", load_data)
            load_value = float(load_data[0].split(":")[1])
            print("load_value : ", load_value)
            load_leg_id = load_data[1].split(":")[1]
            print("load_leg_id", load_leg_id)
            meter_number = load_data[2].split(":")[1]
            print("meter_number : ", meter_number)
            print("@@@@@@@@@@@@@@@@@@@")
            load_date = load_data[3].split(":")[1:]
            print("load_date", load_date)
            date = ":".join(load_date)
            print("date : ", date)
            load_date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S.%f")
            print("load_date : ", load_date)
            load_hour = load_date.hour
            load_minute = load_date.minute
            load_epoch_time = load_data[4].split(":")[1]
            print("epoch", load_epoch_time)
            load_aisle_group = AisleGroup.objects.filter(
                site=site, attached_leg_id=str(load_leg_id)
            )
            print("load_aisle_group :", load_aisle_group)
            # raw load data logic starts here
            RawLoadData.objects.create(
                site=site,
                aisle_group=load_aisle_group[0],
                load_data=load_value,
                created=load_date,
                epoch_time=load_epoch_time,
            )
            print(
                "raw entry created for {} site with leg id {} of load value {} at {}".format(
                    locationId, load_leg_id, load_value, datetime.now()
                )
            )
            # raw load data logic ends here
            if site.is_loadGraph_visible:
                power_source = load_aisle_group[0].aisleGroupName
                print("power source", power_source)
                load_entry = SiteLoadPower.objects.filter(
                    Associated_Site=int(location_id), Meter_Number=meter_number
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
                            load_value,
                        )
                        if monthly_min_load > load_value:
                            print("updating min load")
                            monthly_min_max_load.update(
                                min_load=load_value, min_load_created=today_date
                            )
                            if load_entry.exists():
                                load_entry.update(min_load=load_value)
                        elif monthly_min_load == 0.0:
                            monthly_min_max_load.update(
                                min_load=load_value, min_load_created=today_date
                            )
                            if load_entry.exists():
                                load_entry.update(min_load=load_value)
                        if monthly_max_load < load_value:
                            print("updating max load")
                            monthly_min_max_load.update(
                                max_load=load_value, max_load_created=today_date
                            )
                            if load_entry.exists():
                                load_entry.update(max_load=load_value)
                    else:
                        print("creating first entry for this month")
                        MonthlyMinMaxLoadData.objects.create(
                            site=site,
                            min_load=load_value,
                            max_load=load_value,
                            min_load_created=today_date,
                            max_load_created=today_date,
                            created=today_date,
                            supply_source=power_source,
                        )
                except Exception as err:
                    print("Error in monthly min max load section : ", err)
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
                                            if int(min_epoch_time) < int(
                                                max_epoch_time
                                            ):
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

        # load graph data code ends from here

        elif "SupplyTime" in msg_type:
            try:
                print("Calculating the load run time for ")
                time_source = message.split(",")
                print(time_source[0])
                print(time_source[1])
                print(time_source[2])
                source_run_time = float(time_source[1].split(":")[1])
                source = int(time_source[0].split(":")[1])
                message_time = time_source[3].split(":")[1]
                message_date_time = message_time.split(" ")
                print("This is the supply time for {}".format(source))
                print("Message date : {}".format(message_date_time[0]))
                date = datetime.strptime(message_date_time[0], "%Y-%m-%d")
                print("date : ", date)
                dateHourLowerLimitCheck = date.replace(
                    hour=int(message_date_time[1]), minute=0, second=0, microsecond=0
                )
                print(dateHourLowerLimitCheck)
                dateHourUpperLimitCheck = date.replace(
                    hour=int(message_date_time[1]), minute=59, second=59, microsecond=0
                )
                print(dateHourUpperLimitCheck)
                run_time = SupplyLoadTimeShare.objects.filter(
                    site=int(location_id), power_source=source
                )
                current_hour_runtime = run_time.filter(
                    reading_from__gte=dateHourLowerLimitCheck,
                    reading_from__lte=dateHourUpperLimitCheck,
                )
                print("Checking conditions for run time entry.")
                if current_hour_runtime.exists():
                    print("Updating the supply run time for {}.".format(source))
                    new_run_time = (
                        current_hour_runtime[0].hourly_run_time + source_run_time
                    )
                    current_hour_runtime.update(hourly_run_time=new_run_time)
                    print("Supply run time for {} updated of {}".format(source, site))

                else:
                    try:

                        print(
                            "Creating new entry for run time of {} in {}".format(
                                source, site
                            )
                        )
                        # logic to save percentage run for different power sources.
                        today = datetime.now()
                        print("run time objects is :", run_time)
                        monthly_load_share = (run_time.last()).reading_from
                        print("monthly load share is : ", monthly_load_share)
                        if (
                            today.month != monthly_load_share.month
                            and today > monthly_load_share
                        ):
                            previous_month_last_date = today - timedelta(days=1)
                            previous_month_first_date = (
                                previous_month_last_date.replace(day=1)
                            )
                            monthly_run_time = SupplyLoadTimeShare.objects.filter(
                                site=location_id
                            )
                            monthly_total_run_time = monthly_run_time.filter(
                                reading_from__date__gte=previous_month_first_date,
                                reading_from__date__lte=previous_month_last_date,
                            )
                            total_time = sum(
                                [i.hourly_run_time for i in monthly_total_run_time]
                            )
                            print(
                                "Total runtime for last month = {}".format(total_time)
                            )
                            for j in monthly_run_time.distinct("power_source"):
                                single_power_monthly_runtime = (
                                    monthly_total_run_time.filter(
                                        power_source=j.power_source
                                    )
                                )
                                print(
                                    "Calculating and creating entry for power source {} for site {}".format(
                                        j.power_source, site.site_name
                                    )
                                )
                                single_source_total_time = sum(
                                    [
                                        i.hourly_run_time
                                        for i in single_power_monthly_runtime
                                    ]
                                )
                                single_source_percentage = (
                                    single_source_total_time / total_time
                                ) * 100
                                print(
                                    "The time based run percentage for power source {} is {}".format(
                                        j.power_source, single_source_percentage
                                    )
                                )
                                # *********************************************************** for energy based percentage.
                                # associated_aisle_group = AisleGroup.objects.filter(site_id=site, )
                                # ***********************************************************
                                for_month = previous_month_first_date.strptime("%M %Y")
                                MonthlyLoadSharePercentage.objects.create(
                                    site=site,
                                    power_source=j.power_source,
                                    monthly_time_based_percentage=single_source_percentage,
                                    for_month=for_month,
                                )
                                print(
                                    "Monthly entry created for {} for power source {} for site {}".format(
                                        for_month, j.power_source, site.site_name
                                    )
                                )
                    except Exception as err:
                        print(
                            "exception in monthly load share percentage table : ", err
                        )
                    print("Find the last value of total run time.")
                    dateHourLowerLimitCheck1 = dateHourLowerLimitCheck - timedelta(
                        hours=1
                    )
                    dateHourUpperLimitCheck1 = dateHourUpperLimitCheck - timedelta(
                        hours=1
                    )
                    previous_hour_run_time = run_time.filter(
                        reading_from__gte=dateHourLowerLimitCheck1,
                        reading_from__lte=dateHourUpperLimitCheck1,
                    )
                    if previous_hour_run_time.exists():
                        print("Previous hour entry found, data is consistent.")
                        # print("Creating new entry for {} in site {}".format(source, site))
                        SupplyLoadTimeShare.objects.create(
                            site=site,
                            power_source=source,
                            hourly_run_time=source_run_time,
                            reading_from=dateHourLowerLimitCheck,
                            reading_to=dateHourUpperLimitCheck,
                        )
                        print(
                            "New hourly run time entry for {} in {} created.".format(
                                source, site
                            )
                        )
                    else:
                        if (
                            run_time.count() > 0
                        ):  # If not the first ever entry for this site.
                            print("Previous hour entry not found, data loss suspected.")
                            last_runtime_entry = run_time.last()
                            loss_time = (
                                today - last_runtime_entry.reading_from
                            ).total_seconds()
                            last_synced_hour = datetime.strftime(
                                last_runtime_entry.reading_from, "%Y-%m-%d %H:%M:%S.%f"
                            )
                            print("Reading lost for {} seconds.".format(loss_time))
                            print(
                                "Starting recovery mechanism for runtime data for source {}".format(
                                    source
                                )
                            )
                            topictosend = (
                                "/Acclivate/iOmniControl/"
                                + str(location_id)
                                + "/"
                                + gw_id
                                + "/in/"
                                + "sync"
                                + "/loadTime"
                                + "/state"
                            )
                            msg = (
                                "Power_source : "
                                + str(source)
                                + ", Missed_consumption_time_in_secs : "
                                + str(loss_time)
                                + ", Last_synced_hour : "
                                + last_synced_hour
                            )
                            client.publish(topictosend, msg, qos=0, retain=False)
                            print(
                                "Recovery message for runtime sent to {} gateway for power source {}.".format(
                                    site, source
                                )
                            )
                        else:
                            print("Creating first entry for this power source.")
                            SupplyLoadTimeShare.objects.create(
                                site=site,
                                power_source=source,
                                hourly_run_time=source_run_time,
                                reading_from=dateHourLowerLimitCheck,
                                reading_to=dateHourUpperLimitCheck,
                            )
                            print(
                                "First ever hourly run time entry for {} in {} created.".format(
                                    source, site
                                )
                            )
            except Exception as e:
                print("Exception in load run time block.")
                print("This is the exception : {}".format(e))

        if "recovery" in msg_type:
            if "dailyConsumption" in msg_subtype:
                try:
                    print(
                        "Starting recovery for daily consumption for site {}.".format(
                            site
                        )
                    )
                    (
                        aisle_group_id,
                        recovery_dates,
                        unit_consumptions,
                        gw_total_cumulative,
                    ) = re.search(
                        r"Aisle_group_id : (.*); Recovery_Dates : (.*); Unit_consumptions : (.*);"
                        r" GW_Total_cumulative : (.*)",
                        message,
                    ).groups()
                    dates = recovery_dates.split(",")
                    daily_consumptions = unit_consumptions.split(",")
                    # daily_consumptions = map(float, consumptions)
                    aisle_group = AisleGroup.objects.filter(
                        site=site, attached_leg_id=aisle_group_id
                    )
                    aisle_group_status, aisle_group_active, daily_saving = (
                        False,
                        False,
                        0.0,
                    )
                    if aisle_group[0].is_visible:
                        aisle_group_status = True
                    if aisle_group[0].is_active:
                        aisle_group_active = True
                    # if len(dates) == len(consumptions) :  # for advance recovery mechanism
                    for i in range(len(dates) - 1):
                        date = datetime.strptime(dates[i], "%Y-%m-%d")
                        if daily_consumptions[i] == "ERROR404":
                            daily_unit_consumption = 0.0
                        else:
                            daily_unit_consumption = float(daily_consumptions[i])
                        daily_entry = DailySiteReading.objects.filter(
                            associated_Site=site,
                            leg_id=aisle_group_id,
                            reading_for=date,
                        )
                        daily_saving, aisle_group_baseline = 0.0, 0.0
                        if aisle_group_active:
                            aisle_group_baseline = SiteBaseline.objects.filter(
                                associated_site_id=int(location_id),
                                leg_id=str(aisle_group_id),
                                baseline_from__lte=date,
                                baseline_to__gte=date,
                            )
                            if aisle_group_baseline:
                                aisle_group_baseline = aisle_group_baseline[
                                    0
                                ].baseline_value
                            else:
                                aisle_group_baseline = (
                                    SiteBaseline.objects.filter(
                                        associated_site_id=int(location_id),
                                        leg_id=str(aisle_group_id),
                                    )
                                    .last()
                                    .baseline_value
                                )
                            print("Now calculating saving for {}.".format(date))
                            daily_saving = aisle_group_baseline - daily_unit_consumption
                        if daily_entry.exists():
                            print(
                                "Updating the recovery unit in aisle group {} for {}".format(
                                    aisle_group_id, date
                                )
                            )
                            daily_entry.update(
                                unit_consumption=daily_unit_consumption,
                                daily_baseline_value=aisle_group_baseline,
                                energy_saved=daily_saving,
                            )
                            print(
                                "Updated with {} units consumption and {} units saving.".format(
                                    daily_unit_consumption, daily_saving
                                )
                            )
                        else:
                            print("Creating new daily consumption entry for recovery.")
                            DailySiteReading.objects.create(
                                associated_Site=site,
                                aisle_group=aisle_group[0],
                                leg_id=aisle_group_id,
                                unit_consumption=daily_unit_consumption,
                                daily_baseline_value=aisle_group_baseline,
                                energy_saved=daily_saving,
                                reading_for=date,
                                is_visible=True,
                            )
                            print(
                                "Consumption and saving calculated and recovered for {}.".format(
                                    aisle_group_id
                                )
                            )
                except Exception as e:
                    print("Exception in daily consumption recovery block.")
                    print("This is the exception : {}".format(e))

            elif "hourlyConsumption" in msg_subtype:
                try:
                    print(
                        "Starting recovery for hourly consumption for site {}.".format(
                            site
                        )
                    )
                    (
                        aisle_group_id,
                        recovery_hours,
                        unit_consumptions,
                        gw_total_cumulative,
                    ) = re.search(
                        r"Aisle_group_id : (.*); Recovery_Hours : (.*); Unit_consumptions : (.*);"
                        r" GW_total_cumulative : (.*)",
                        message,
                    ).groups()
                    hours = recovery_hours.split(",")
                    hourly_consumptions = unit_consumptions.split(",")
                    # hourly_consumptions = map(float, hourly_consumptions)
                    aisle_group = AisleGroup.objects.filter(
                        site=site, attached_leg_id=aisle_group_id
                    )
                    aisle_group_status, aisle_group_active, daily_saving = (
                        False,
                        False,
                        0.0,
                    )
                    if aisle_group[0].is_visible:
                        aisle_group_status = True
                    if aisle_group[0].is_active:
                        aisle_group_active = True
                    # if len(hours) == len(hourly_consumptions) :  # for advance recovery mechanism
                    for i in range(len(hours) - 1):
                        print(hours[i])
                        dateHour = datetime.strptime(hours[i], "%Y-%m-%d %H:%M:%S.%f")
                        print(dateHour)
                        dateHourLowerLimitCheck = dateHour.replace(
                            minute=0, second=0, microsecond=0
                        )
                        dateHourUpperLimitCheck = dateHour.replace(
                            minute=59, second=59, microsecond=0
                        )
                        if hourly_consumptions[i] == "ERROR404":
                            hourly_unit_consumption = 0.0
                            # Saving logic to be added here to handle spike for any hour.(Save the hours for which
                            # the readings have been missed and form a new baseline for hour with spike.)
                        else:
                            hourly_unit_consumption = float(hourly_consumptions[i])
                        print(hourly_unit_consumption)
                        hourly_entry = HourlySiteReading.objects.filter(
                            associated_Site=site,
                            leg_id=aisle_group_id,
                            reading_from=dateHourLowerLimitCheck,
                            reading_to=dateHourUpperLimitCheck,
                        )
                        hourly_saving, leg_hourly_baseline = 0.0, 0.0
                        if aisle_group_active:
                            aisle_group_baseline = SiteBaseline.objects.filter(
                                associated_site_id=int(location_id),
                                leg_id=str(aisle_group_id),
                                baseline_from__lte=dateHour.date(),
                                baseline_to__gte=dateHour.date(),
                            )
                            if aisle_group_baseline:
                                leg_hourly_baseline = (
                                    aisle_group_baseline[0].baseline_value
                                    / aisle_group_baseline[0].working_hours
                                )
                            else:
                                aisle_group_baseline = SiteBaseline.objects.filter(
                                    associated_site_id=int(location_id),
                                    leg_id=str(aisle_group_id),
                                ).last()
                                leg_hourly_baseline = (
                                    aisle_group_baseline.baseline_value
                                    / aisle_group_baseline.working_hours
                                )
                            print("Now calculating saving for {}.".format(dateHour))
                            hourly_saving = (
                                leg_hourly_baseline - hourly_unit_consumption
                            )
                        if hourly_entry.exists():
                            print(
                                "Updating the recovery unit in aisle group {} for {}".format(
                                    aisle_group_id, dateHour
                                )
                            )
                            hourly_entry.update(
                                unit_consumption=hourly_unit_consumption,
                                hourly_baseline_value=leg_hourly_baseline,
                                energy_saved=hourly_saving,
                            )
                            print(
                                "Updated with {} units consumption and {} units saving.".format(
                                    hourly_unit_consumption, daily_saving
                                )
                            )
                        else:
                            print(
                                "Creating new hourly consumption entry for recovery of {} for {}.".format(
                                    aisle_group_id, dateHour
                                )
                            )
                            HourlySiteReading.objects.create(
                                associated_Site=site,
                                aisle_group=aisle_group[0],
                                leg_id=aisle_group_id,
                                unit_consumption=hourly_unit_consumption,
                                hourly_baseline_value=leg_hourly_baseline,
                                energy_saved=hourly_saving,
                                reading_from=dateHourLowerLimitCheck,
                                reading_to=dateHourUpperLimitCheck,
                                is_visible=True,
                            )
                            print(
                                "Hourly consumption and saving calculated and recovered."
                            )
                except Exception as e:
                    print("Exception in hourly consumption recovery block.")
                    print("This is the exception : {}".format(e))

            elif "loadRuntime" in msg_subtype:
                print("############### inside Load RUn time @@@@@@@@@@@@@@@@@@@")
                try:
                    powerSource, recovery_hours, recovery_load_time = re.search(
                        "Power_source : (.*); Recovery_hours : (.*); Recovery_load_runtime : (.*)",
                        message,
                    ).groups()
                    power_source = SupplyLoadTimeShare.objects.filter(
                        site=site, power_source=int(powerSource)
                    )
                    recovery_hours = recovery_hours.split(",")
                    recovery_load_runtime = recovery_load_time.split(",")
                    print(
                        "This is the load runtime recovery message for {} in {}.".format(
                            power_source[0].get_power_source_display(), site
                        )
                    )
                    for i in range(len(recovery_hours) - 1):
                        entry_datetime = datetime.strptime(
                            recovery_hours[i], "%Y-%m-%d %H:%M:%S.%f"
                        )
                        runtime_entry = power_source.filter(reading_from=entry_datetime)
                        if recovery_load_runtime[i] == "ERROR404":
                            load_runtime = 0
                        else:
                            load_runtime = int(recovery_load_runtime[i])
                        if runtime_entry.exists():
                            runtime_entry.update(hourly_run_time=load_runtime)
                            print("Load runtime updated for {}.".format(entry_datetime))
                        else:
                            print(
                                "Creating new entry for recovery of hour {}".format(
                                    entry_datetime
                                )
                            )
                            SupplyLoadTimeShare.objects.create(
                                site=site,
                                power_source=int(powerSource),
                                hourly_run_time=load_runtime,
                                reading_from=entry_datetime,
                                reading_to=entry_datetime.replace(minute=59, second=59),
                            )
                            print(
                                "New entry successfully created for recovery of hour {}".format(
                                    entry_datetime
                                )
                            )
                except Exception as e:
                    print("Exception in load time recovery block.")
                    print("This is the exception : {}".format(e))
            else:
                print("#####################################################")
                print("****** Received an unknown recovery message. ********")
                print("#####################################################")

        else:
            print("##########################################################")
            print("*********Got an unknown message. Need to check!!**********")
            print("##########################################################")

    client = mqtt.Client("server_paho_client_1")
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect("127.0.0.1", 1883, 60)
    print("MQTT Client is Running >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
    # client.username_pw_set("djgpjqqt","AfTkXiiaov8c")

    # Blocking call that processes network traffic, dispatches callbacks and
    # handles reconnecting.
    # Other loop*() functions are available that give a threaded interface and a
    # manual interface.
    client.loop_forever()


@app.task
def mqtt_client2():
    print("client2")

    # app = Celery('mqtt_client', broker='amqp://guest@localhost/')

    # The callback for when the client receives a CONNACK response from the server.
    def on_connect(client, userdata, flags, rc):
        # logMessage(Constants.TRACE_FLAG_INFO, "Connected with result code " + str(rc))
        print("Connected with result code " + str(rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe("/Acclivate/iOmniControl/#")
        client.subscribe("/sem/iOmniControl/+/+/+/+/state", 1)
        client.subscribe("/AVC_510_delhivery/#")

    # The callback for when a PUBLISH message is received from the server.
    def on_message(client, userdata, msg):
        print("######################")
        print("Topic: ", msg.topic + "  Message: " + str(msg.payload))
        print("######################")
        message = str(msg.payload)
        head = (msg.topic).split("/")
        gw_id = head[4]
        print(gw_id)
        msg_type = (head[6]).split("_")
        msg_subtype = head[7]
        print("This is the message type: ", msg_type)
        location_id = int((gw_id.split("_"))[3])
        site = Site.objects.get(id=location_id)
        print("Location Id is : ", str(location_id))
        print("Site Name : {}".format(site.site_name))
        if "recovery" in msg_type:
            if "dailyConsumption" in msg_subtype:
                try:
                    print(
                        "Starting recovery for daily consumption for site {}.".format(
                            site
                        )
                    )
                    (
                        aisle_group_id,
                        recovery_dates,
                        unit_consumptions,
                        gw_total_cumulative,
                    ) = re.search(
                        r"Aisle_group_id : (.*); Recovery_Date : (.*); Unit_consumptions : (.*);"
                        r" GW_Total_cumulative : (.*)",
                        message,
                    ).groups()
                    dates = recovery_dates.split(",")
                    daily_consumptions = unit_consumptions.split(",")
                    # daily_consumptions = map(float, consumptions)
                    aisle_group = AisleGroup.objects.filter(
                        site=site, attached_leg_id=aisle_group_id
                    )
                    aisle_group_status, aisle_group_active, daily_saving = (
                        False,
                        False,
                        0.0,
                    )
                    if aisle_group[0].is_visible:
                        aisle_group_status = True
                    if aisle_group[0].is_active:
                        aisle_group_active = True
                    # if len(dates) == len(consumptions) :  # for advance recovery mechanism
                    for i in range(len(dates) - 1):
                        date = datetime.strptime(dates[i], "%Y-%m-%d")
                        if daily_consumptions[i] == "ERROR404":
                            daily_unit_consumption = 0.0
                        else:
                            daily_unit_consumption = float(daily_consumptions[i])
                        daily_entry = DailySiteReading.objects.filter(
                            associated_Site=site,
                            leg_id=aisle_group_id,
                            reading_for=date,
                        )
                        daily_saving = 0.0
                        if aisle_group_active:
                            aisle_group_baseline = (
                                SiteBaseline.objects.filter(
                                    associated_site_id=int(location_id),
                                    leg_id=str(aisle_group_id),
                                )
                                .last()
                                .baseline_value
                            )
                            # leg_hourly_baseline = aisle_group_baseline.baseline_value / aisle_group_baseline.working_hours
                            print("Now calculating saving for {}.".format(date))
                            daily_saving = aisle_group_baseline - daily_unit_consumption
                        if daily_entry.exists():
                            print(
                                "Updating the recovery unit in aisle group {} for {}".format(
                                    aisle_group_id, date
                                )
                            )
                            daily_entry.update(
                                unit_consumption=daily_unit_consumption,
                                daily_baseline_value=aisle_group_baseline,
                                energy_saved=daily_saving,
                            )
                            print(
                                "Updated with {} units consumption and {} units saving.".format(
                                    daily_unit_consumption, daily_saving
                                )
                            )
                        else:
                            print("Creating new daily consumption entry for recovery.")
                            DailySiteReading.objects.create(
                                associated_Site=site,
                                aisle_group=aisle_group[0],
                                leg_id=aisle_group_id,
                                unit_consumption=daily_unit_consumption,
                                daily_baseline_value=aisle_group_baseline,
                                energy_saved=daily_saving,
                                reading_for=date,
                                is_visible=True,
                            )
                            print(
                                "Consumption and saving calculated and recovered for {}.".format(
                                    aisle_group_id
                                )
                            )
                except Exception as e:
                    print("Exception in daily consumption recovery block.")
                    print("This is the exception : {}".format(e))

            elif "hourlyConsumption" in msg_subtype:
                try:
                    print(
                        "Starting recovery for hourly consumption for site {}.".format(
                            site
                        )
                    )
                    (
                        aisle_group_id,
                        recovery_hours,
                        unit_consumptions,
                        gw_total_cumulative,
                    ) = re.search(
                        r"Aisle_group_id : (.*); Recovery_Hours : (.*); Unit_consumptions : (.*);"
                        r" GW_Total_cumulative : (.*)",
                        message,
                    ).groups()
                    hours = recovery_hours.split(",")
                    hourly_consumptions = unit_consumptions.split(",")
                    # hourly_consumptions = map(float, hourly_consumptions)
                    aisle_group = AisleGroup.objects.filter(
                        site=site, attached_leg_id=aisle_group_id
                    )
                    aisle_group_status, aisle_group_active, daily_saving = (
                        False,
                        False,
                        0.0,
                    )
                    if aisle_group[0].is_visible:
                        aisle_group_status = True
                    if aisle_group[0].is_active:
                        aisle_group_active = True
                    # if len(hours) == len(hourly_consumptions) :  # for advance recovery mechanism
                    for i in range(len(hours) - 1):
                        dateHour = datetime.strptime(hours[i], "%Y-%m-%d %H:%M:%S")
                        if hourly_consumptions[i] == "ERROR404":
                            hourly_unit_consumption = 0.0
                            # Saving logic to be added here to handle spike for any hour.(Save the hours for which
                            # the readings have been missed and form a new baseline for hour with spike.)
                        else:
                            hourly_unit_consumption = float(hourly_consumptions[i])
                        hourly_entry = HourlySiteReading.objects.filter(
                            associated_Site=site,
                            leg_id=aisle_group_id,
                            reading_from__gte=dateHour,
                            reading_to__lte=dateHour,
                        )
                        hourly_saving = 0.0
                        if aisle_group_active:
                            aisle_group_baseline = SiteBaseline.objects.filter(
                                associated_site_id=int(location_id),
                                leg_id=str(aisle_group_id),
                            ).last()
                            leg_hourly_baseline = (
                                aisle_group_baseline.baseline_value
                                / aisle_group_baseline.working_hours
                            )
                            print("Now calculating saving for {}.".format(dateHour))
                            hourly_saving = (
                                leg_hourly_baseline - hourly_unit_consumption
                            )
                        if hourly_entry.exists():
                            print(
                                "Updating the recovery unit in aisle group {} for {}".format(
                                    aisle_group_id, dateHour
                                )
                            )
                            hourly_entry.update(
                                unit_consumption=hourly_unit_consumption,
                                hourly_baseline_value=leg_hourly_baseline,
                                energy_saved=hourly_saving,
                            )
                            print(
                                "Updated with {} units consumption and {} units saving.".format(
                                    hourly_unit_consumption, daily_saving
                                )
                            )
                        else:
                            print(
                                "Creating new hourly consumption entry for recovery of {} for {}.".format(
                                    aisle_group_id, dateHour
                                )
                            )
                            HourlySiteReading.objects.create(
                                associated_Site=site,
                                aisle_group=int(aisle_group_id),
                                leg_id=aisle_group_id,
                                unit_consumption=hourly_unit_consumption,
                                hourly_baseline_value=leg_hourly_baseline,
                                energy_saved=hourly_saving,
                                reading_from=dateHour.replace(minute=0, second=0),
                                reading_to=dateHour.replace(minute=59, second=59),
                                is_visible=True,
                            )
                            print(
                                "Hourly consumption and saving calculated and recovered."
                            )
                except Exception as e:
                    print("Exception in hourly consumption recovery block.")
                    print("This is the exception : {}".format(e))

            elif "loadTime" in msg_subtype:
                try:
                    data = re.search(
                        "Power_source : (.*); Recovery_hours : (.*); Recovery_load_runtime : (.*)"
                    ).groups()
                    power_source = SupplyLoadTimeShare.objects.filter(
                        site=site, power_source=int(data[0])
                    )
                    recovery_hours = data[1].split(",")
                    recovery_load_runtime = data[2].split(",")
                    print(
                        "This is the load runtime recovery message for {} in {}.".format(
                            power_source[0].get_power_source_display, site
                        )
                    )
                    for i in range(len(recovery_hours) - 1):
                        enrty_datetime = datetime.strptime(
                            recovery_hours[i], "%Y-%m-%d %H:%M:%S"
                        )
                        runtime_entry = power_source.filter(reading_from=entry_datetime)
                        if recovery_load_runtime[i] == "ERROR404":
                            load_runtime = 0
                        else:
                            load_runtime = int(recovery_load_runtime[i])
                        if runtime_entry.exists():
                            runtime_entry.update(hourly_run_time=load_runtime)
                            print("Load runtime updated for {}.".format(entry_datetime))
                        else:
                            print(
                                "Creating new entry for recovery of hour {}".format(
                                    entry_datetime
                                )
                            )
                            SupplyLoadTimeShare.objects.create(
                                site=site,
                                power_source=int(data[0]),
                                hourly_run_time=load_runtime,
                                reading_from=enrty_datetime,
                                reading_to=enrty_datetime.replace(minute=59, second=59),
                            )
                            print(
                                "New entry successfully created for recovery of hour {}".format(
                                    entry_datetime
                                )
                            )
                except Exception as e:
                    print("Exception in hourly consumption recovery block.")
                    print("This is the exception : {}".format(e))
            else:
                print("#####################################################")
                print("****** Received an unknown recovery message. ********")
                print("#####################################################")

        else:
            print("##########################################################")
            print("*********Got an unknown message. Need to check!!**********")
            print("##########################################################")

    client = mqtt.Client("server_paho_client_2")
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect("127.0.0.1", 1883, 60)
    print("MQTT Client is Running >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")

    # client.username_pw_set("djgpjqqt","AfTkXiiaov8c")

    # Blocking call that processes network traffic, dispatches callbacks and
    # handles reconnecting.
    # Other loop*() functions are available that give a threaded interface and a
    # manual interface.
    client.loop_forever()


# mqtt_client()
