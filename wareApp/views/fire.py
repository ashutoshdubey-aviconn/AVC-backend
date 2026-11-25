"""Fire alarm and fire-equipment endpoints."""

from datetime import datetime

from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    Email_History,
    FireEquipmentsSystem,
    FireEquipmentsSystemType,
    FirePumpAlarm,
    Site,
)
from wareApp.utility import entryExit, logger


class FireAlarm(APIView):
    """API view for /api/fireAlarm/ (POST; Login required (default)). Reads AisleGroup, FirePumpAlarm,
    Site. Takes site_id. Returns data, status.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST /api/fireAlarm/. Request fields: site_id. Response keys: data, status.

        Origin: Ashu (changed from main)
        """
        data = request.data
        logger.debug("%s %s", "data : ", data)
        site_id = data.get("site_id", "")
        site = Site.objects.get(id=site_id)
        logger.debug("%s %s", "site : ", site)
        all_leg = AisleGroup.objects.distinct("aisleGroupName").filter(site=site)
        logger.debug("%s %s", "all_leg", all_leg)
        systemlist = []
        for i in all_leg:
            aisles = AisleGroup.objects.filter(
                site=site, aisleGroupName=i.aisleGroupName
            )
            logger.debug("%s %s", "aisles", aisles)
            firealarm = FirePumpAlarm.objects.filter(Site=site, aisleGroup__in=aisles)
            logger.debug("%s %s", "firealarm:", firealarm)
            if firealarm.exists:
                for j in firealarm:
                    systemlist.append(
                        {
                            "aislename": j.aisleGroup.aisleGroupName,
                            "R_Voltage": j.r_volt,
                            "Y_Voltage": j.y_volt,
                            "B_Voltage": j.b_volt,
                            "current_date": j.Updated_on,
                            "manual_time": j.manual_mode_updated_time,
                            "auto_mode": j.auto_mode_updated_time,
                            "off_mode": j.off_mode_time,
                            "motor_status": j.motor_status,
                            "motor_status_time": j.motor_status_time,
                        }
                    )
        return Response({"status": 200, "data": systemlist})


class EmailHistory(APIView):

    """API view for /api/emailhistory/ (POST; Login required (default)). Reads Email_History, Site.
    Takes site_id. Returns data, message, status.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST /api/emailhistory/. Request fields: site_id. Response keys: data, message, status.

        Origin: Ashu (changed from main)
        """
        site_id = request.data.get("site_id")

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"status": 404, "message": "Site not found"})

        emailhistory = (
            Email_History.objects.filter(fire_site=site)
            .select_related("fire_site", "deviceName")
            .order_by("-created")
        )

        email_list = [
            {
                "site": e.fire_site.site_name,
                "device_name": e.deviceName.aisleGroupName,
                "email_for": e.email_for,
                "datetime": e.created,
            }
            for e in emailhistory
        ]

        return Response({"status": 200, "data": email_list})


class FireEquipmentSystemAdd(APIView):
    """API view for /api/saveInventoryData/ (POST; Login required (default)). Saves to
    FireEquipmentsSystem. Reads FireEquipmentsSystemType. Takes assetNo, deviceName, id,
    last_service, location, modelNo, next_service, row_id, updated_by, warrenty. Returns msg,
    status.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST /api/saveInventoryData/. Request fields: assetNo, deviceName, id, last_service,
        location, modelNo, next_service, row_id, updated_by, warrenty. Response keys: msg, status.

        Origin: Ashu (changed from main)
        """
        data = request.data
        logger.debug("%s %s", "data", data)
        device_id = data.get("id", "")
        deviceName = data.get("deviceName")
        id = int(data.get("row_id"))
        assetno = data.get("assetNo", "")
        model_no = data.get("modelNo", "")
        loaction = data.get("location", "")
        updatedby = data.get("updated_by", "")
        warrenty_till = data.get("warrenty", "")
        last_service = data.get("last_service", "")
        next_service = data.get("next_service", "")
        fire = FireEquipmentsSystemType.objects.get(id=id)
        try:
            if device_id != "":
                msg = "record update"
                FireEquipmentsSystem.objects.filter(id=int(device_id)).update(
                    deviceType=fire,
                    assetNo=assetno,
                    updatedBy=updatedby,
                    modelNo=model_no,
                    loaction=loaction,
                    Warrenty_till=datetime.strptime(warrenty_till, "%Y-%m-%d").date(),
                    last_service=datetime.strptime(last_service, "%Y-%m-%d").date(),
                    next_service=datetime.strptime(next_service, "%Y-%m-%d").date(),
                )
            else:
                msg = "record saved"
                firesystem = FireEquipmentsSystem.objects.create(
                    deviceType=fire,
                    assetNo=assetno,
                    updatedBy=updatedby,
                    modelNo=model_no,
                    loaction=loaction,
                    Warrenty_till=datetime.strptime(warrenty_till, "%Y-%m-%d").date(),
                    last_service=datetime.strptime(last_service, "%Y-%m-%d").date(),
                    next_service=datetime.strptime(next_service, "%Y-%m-%d").date(),
                )
            return Response({"status": 200, "msg": msg})
        except Exception as err:
            return Response({"status": 500})


class FireEquipmentSystemFetch(APIView):
    """API view for /api/fireDevicefetchdata/ (POST; Login required (default)). Reads
    FireEquipmentsSystem, FireEquipmentsSystemType. Takes row_id. Returns data, result.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST /api/fireDevicefetchdata/. Request fields: row_id. Response keys: data, result.

        Origin: Ashu (changed from main)
        """
        data = request.data
        logger.debug("%s %s", "data : ", data)
        row_id = data.get("row_id", "")
        fireEquipments = FireEquipmentsSystemType.objects.filter(id=row_id)
        logger.debug("%s %s", "fireEquipments", fireEquipments)
        fire = FireEquipmentsSystem.objects.filter(deviceType__in=fireEquipments)
        logger.debug("%s %s", "fire:", fire)
        data_list = []
        for i in fire:
            data_list.append(
                {
                    "id": i.id,
                    "updatedby": i.updatedBy,
                    "deviceName": i.deviceType.devicename,
                    "assetNo": i.assetNo,
                    "modelsNo": i.modelNo,
                    "location": i.loaction,
                    "warrentDate": i.Warrenty_till,
                    "last_serviceDate": i.last_service,
                    "next_serviceDate": i.next_service,
                }
            )
        return Response({"result": 1, "data": data_list})


class FireEquiSystemTypefetch(APIView):
    """API view for /api/fireDeviceTypefetch/ (POST; Login required (default)). Reads
    FireEquipmentsSystemType, Site. Takes site_id. Returns data, result.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST /api/fireDeviceTypefetch/. Request fields: site_id. Response keys: data, result.

        Origin: Ashu (changed from main)
        """
        data = request.data
        logger.debug("%s %s", "data :", data)
        site_id = data.get("site_id", "")
        site = Site.objects.get(id=site_id)
        logger.debug("%s %s", "site : ", site)
        fireequipment = FireEquipmentsSystemType.objects.filter(site=site)
        logger.debug("%s %s", "fireequipment", fireequipment)
        list = []
        for i in fireequipment:
            list.append(
                {"row_id": i.id, "deviceName": i.devicename, "categories": i.categories}
            )
        return Response({"result": 1, "data": list})


class FireEquiSystemTypeAdd(APIView):
    """API view for /api/fireDeviceTypeAdd/ (POST; Login required (default)). Saves to
    FireEquipmentsSystemType. Reads Site. Takes category, deviceName.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST /api/fireDeviceTypeAdd/. Request fields: category, deviceName. Response keys: built in
        code (not a fixed dict).

        Origin: Ashu (changed from main)
        """
        data = request.data
        logger.debug("%s %s", "data:", data)
        devicename = data.get("deviceName", "")
        category = data.get("category", "")
        site = Site.objects.get(id=23)
        firesystem = FireEquipmentsSystemType(
            site=site, devicename=devicename, categories=category
        )
        firesystem.save()
        return Response("Data saved sucessfully")


class SnapshotApi(APIView):
    """API view for /api/snapShotApi/ (POST; Login required (default)). Reads FireEquipmentsSystem.
    Takes site_id. Returns data, expiredDevice, status, totalDevices, warrenty.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST /api/snapShotApi/. Request fields: site_id. Response keys: data, expiredDevice, status,
        totalDevices, warrenty.

        Origin: Ashu (changed from main)
        """
        data = request.data
        site_id = data.get("site_id", "")
        current_date = datetime.now()
        date = current_date.date()
        totalDevices = FireEquipmentsSystem.objects.all().count()
        t = FireEquipmentsSystem.objects.all()
        logger.debug("%s %s", "totalDevices", totalDevices)
        expiredDevice = FireEquipmentsSystem.objects.filter(
            next_service__lte=date
        ).count()
        warrentyDeviceList = []
        warrenty = FireEquipmentsSystem.objects.filter(Warrenty_till__lte=date).count()
        logger.debug("%s %s", "warrenty : ", warrenty)
        warrentyDevices = FireEquipmentsSystem.objects.filter(Warrenty_till__lte=date)
        for i in warrentyDevices:
            warrentyDeviceList.append(
                {
                    "id": i.id,
                    "deviceName": i.deviceType.devicename,
                    "assetNo": i.assetNo,
                    "modelsNo": i.modelNo,
                    "location": i.loaction,
                    "warrentDate": i.Warrenty_till,
                    "last_serviceDate": i.last_service,
                    "next_serviceDate": i.next_service,
                }
            )
            # print("warrenty :",warrentyDeviceList)

        return Response(
            {
                "status": 200,
                "totalDevices": totalDevices,
                "warrenty": warrenty,
                "expiredDevice": expiredDevice,
                "data": warrentyDeviceList,
            }
        )


class ExpiredDevicesListApi(APIView):
    """API view for /api/expireddevicesList/ (POST; Login required (default)). Reads
    FireEquipmentsSystem. Takes site_id. Returns data, status.

    Origin: main (unchanged)
    """
    def post(self, request):
        """POST /api/expireddevicesList/. Request fields: site_id. Response keys: data, status.

        Origin: main (unchanged)
        """
        data = request.data
        site_id = data.get("site_id", "")
        current_date = datetime.now()
        date = current_date.date()
        list = []
        expiredDevice = FireEquipmentsSystem.objects.filter(next_service__lte=date)
        for i in expiredDevice:
            list.append(
                {
                    "id": i.id,
                    "deviceName": i.deviceType.devicename,
                    "modelsNo": i.modelNo,
                    "assetNo": i.assetNo,
                    "location": i.loaction,
                    "warrentDate": i.Warrenty_till,
                    "last_serviceDate": i.last_service,
                    "next_serviceDate": i.next_service,
                }
            )
        return Response({"status": 200, "data": list})


class fireEquiSystemDelete(APIView):
    """API view for /api/deleteInventoryData/ (POST; Login required (default)). Saves to
    FireEquipmentsSystem. Takes id. Returns msg, status.

    Origin: main (unchanged)
    """
    @entryExit
    def post(self, request):
        """POST /api/deleteInventoryData/. Request fields: id. Response keys: msg, status.

        Origin: main (unchanged)
        """
        data = request.data
        row = data.get("id")
        FireEquipmentsSystem.objects.filter(id=int(row)).delete()
        # site = Site.objects.get(id=23)
        # firesystem = FireEquipmentsSystem(id=row)
        # firesystem.delete()
        return Response({"status": 200, "msg": "Data deleted"})
