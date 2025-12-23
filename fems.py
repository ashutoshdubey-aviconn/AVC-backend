import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from wareApp.models import *
from wareApp.views import *
from wareApp.sendmail import *
import time
from datetime import datetime, timedelta


def fems():
    date = datetime.now()
    oneWeekBeforDate = date+timedelta(days=8)
    fourDaysAfterDate = date-timedelta(days=4)
    device = []
    oneWeekBefore = FireEquipmentsSystem.objects.filter(next_service=oneWeekBeforDate.date())
    print("oneWeekBefore",oneWeekBefore)
    if oneWeekBefore.exists():
        for i in oneWeekBefore:
            device.append({"deviceType":i.deviceType.devicename,"modelNo":i.modelNo,"assetNo":i.assetNo,
                               "loaction":i.loaction,"last_service":i.last_service, "next_service":i.next_service})
            print(device)
        if len(device) > 0:
            send_email = send_mail_fire_equipments_system_8days_before(device, "komalbhati8527@gmail.com")
            print("{} mail send Successfully for all devices before 8 days".format(datetime.now()))

    else:
        print("One week before any Service not expired of any devices")
    time.sleep(3)
    device.clear()
    fourDyasAfter = FireEquipmentsSystem.objects.filter(next_service=fourDaysAfterDate.date())
    if fourDyasAfter.exists():
        for i in fourDyasAfter:
            device.append({"deviceType": i.deviceType.devicename, "modelNo": i.modelNo,"assetNo":i.assetNo,
                           "loaction": i.loaction, "last_service": i.last_service, "next_service": i.next_service})
            print(device)
        if len(device) > 0:
            send_email = send_mail_fire_equipments_system_after4days(device, "komalbhati8527@gmail.com")
            print("{} mail send Successfully for all devices after 4 days".format(datetime.now()))
    else:
        print("After 4 days any Service not expired of any device")

fems()



