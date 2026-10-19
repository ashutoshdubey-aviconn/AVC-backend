"""Lights / fans / average device data."""

from datetime import datetime

from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AisleGroup, DailySiteReading, FansData, LightsData, Site
from wareApp.utility import entryExit, logger


class LightsDataApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data :", data)
        data = LightsData.objects.all().order_by("-id")
        list = []
        for i in data:
            list.append(
                {
                    "areaName": i.areaName,
                    "totalLights": i.totalLights,
                    "18Watt": i.watt_18_Lights,
                    "20Watt": i.watt_20_Lights,
                    "24Watt": i.watt_24_Lights,
                    "36Watt": i.watt_36_Lights,
                    "40Watt": i.watt_40_Lights,
                    "totalWattLights": i.totalWattLights,
                    "totalUnits": i.totalUnits,
                }
            )
        return Response({"status": 200, "data": list})


class FansDataApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        data = FansData.objects.all().order_by("id")
        list = []
        for i in data:
            list.append(
                {
                    "areaName": i.areaName,
                    "totalFans": i.totalFans,
                    "80watt": i.watt_80_Lights,
                    "100watt": i.watt_100_Lights,
                    "totalWattFans": i.totalWattFans,
                    "totalUnits": i.totalUnits,
                }
            )
        return Response({"status": 200, "data": list})


class avgDataApi(APIView):
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data%%%%%%", data)

        # Get site_id with proper parameter name and validation
        site_id = data.get("site_id") or data.get("siteId", "")
        if not site_id:
            return Response({"status": 400, "error": "site_id is required"}, status=400)
        try:
            site_id = int(site_id)
        except (ValueError, TypeError):
            return Response(
                {"status": 400, "error": "site_id must be a valid integer"}, status=400
            )

        # Handle virtual site mapping
        if site_id == 34:
            site_id = 29

        from_date = data.get("from_date", "")
        till_date = data.get("till_date", "")

        if not from_date or not till_date:
            return Response(
                {"status": 400, "error": "from_date and till_date are required"},
                status=400,
            )

        logger.debug("%s %s", "from_date", from_date)

        try:
            fromDate = datetime.strptime(from_date, "%Y-%m-%d")
            tillDate = datetime.strptime(till_date, "%Y-%m-%d")
        except ValueError as e:
            return Response(
                {"status": 400, "error": f"Invalid date format: {str(e)}"}, status=400
            )

        logger.debug("%s %s", "fromDate", fromDate)

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response(
                {"status": 404, "error": f"Site with id {site_id} not found"},
                status=404,
            )

        days = tillDate - fromDate
        totaldays = days.days + 1
        logger.debug("%s %s", "Totaldays :", totaldays)
        energyConsumed = 0.0
        avgData = 0.0

        # Use the validated site_id for virtual site mapping
        original_site_id = data.get("site_id") or data.get("siteId", "")
        if int(original_site_id) == 34:
            aisle_group = AisleGroup.objects.filter(
                attached_leg_id__in=[259, 260, 261, 276, 710]
            )
        else:
            aisle_group = AisleGroup.objects.filter(
                virtual_siteID=site_id, is_visible=True
            )
        all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
        daily = DailySiteReading.objects.filter(
            aisle_group__virtual_siteID=site,
            reading_for__gte=fromDate,
            leg_id__in=all_leg_id,
            reading_for__lte=tillDate,
        )
        logger.debug("%s %s", "daily : ", daily)
        if daily.exists():
            for i in daily:
                energyConsumed += i.unit_consumption
            avgData = round(energyConsumed / totaldays, 2)
        return Response(
            {
                "status": 200,
                "value": avgData,
                "energyConsumed": round(energyConsumed, 2),
                "totalDays": totaldays,
            }
        )
