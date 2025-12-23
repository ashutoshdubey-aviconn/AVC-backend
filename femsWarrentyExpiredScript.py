import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from wareApp.models import *
from wareApp.views import *
from wareApp.sendmail import *
import time
from datetime import datetime, timedelta


def WarrantyExpiredFEMS():
    date = datetime.now()
    before30daysDate = date + timedelta(days=30)
    before45daysDate = date+timedelta(days=45)
    device = []
    before30days = FireEquipmentsSystem.objects.filter(Warrenty_till=before30daysDate.date())
    if before30days.exists():
        for i in before30days:
            device.append({"deviceType": i.deviceType.devicename, "modelNo": i.modelNo,"assetNo":i.assetNo,
                           "loaction": i.loaction,"Warrenty_till":i.Warrenty_till, "last_service": i.last_service, "next_service": i.next_service})
            print(device)
        if len(device) > 0:
            send_email = send_mail_fire_equipments_system_30days_before(device, "komalbhati8527@gmail.com")
            print("{} mail send Successfully for all Warranty expired devices before 30 days.".format(datetime.now()))
    else:
        print("30 days before any device warranty not expired.")
    time.sleep(3)
    device.clear()
    before45days = FireEquipmentsSystem.objects.filter(Warrenty_till=before45daysDate.date())
    print("oneWeekBefore",before45days)
    if before45days.exists():
        for i in before45days:
            device.append({"deviceType":i.deviceType.devicename,"modelNo":i.modelNo,"assetNo":i.assetNo,
                               "loaction":i.loaction, "Warrenty_till":i.Warrenty_till,"last_service":i.last_service, "next_service":i.next_service})
            print(device)
        if len(device) > 0:
            send_email = send_mail_fire_equipments_system_45days_before(device, "komalbhati8527@gmail.com")
            print("{} mail send Successfully for all Warranty expired devices before 45 days.".format(datetime.now()))

    else:
        print("45 days before any device warranty not expired.")

WarrantyExpiredFEMS()




