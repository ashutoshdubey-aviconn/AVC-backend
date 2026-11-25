"""Lights / fans / average device data."""

from datetime import datetime

from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AisleGroup, DailySiteReading, FansData, LightsData, Site
from wareApp.utility import entryExit, logger


class LightsDataApi(APIView):
    # Merged from the colleague's code (54313d5, views/fire_views.py), 2026-11-21:
    # reads only the needed columns with .values(). Same response as before.
    # His AllowAny is not taken: this API keeps the default (login required).
    """API view for /api/lightsDataApi/ (POST; Login required (default)). Reads LightsData. Returns
    data, status.

    Origin: Daksh (merged 2026-11-21 from 54313d5, views/fire_views.py)
    """
    @entryExit
    def post(self, request):
        """POST /api/lightsDataApi/. No request fields. Response keys: data, status.

        Origin: Daksh (merged 2026-11-21 from 54313d5, views/fire_views.py)
        """
        lights_data = LightsData.objects.values(
            "areaName",
            "totalLights",
            "watt_18_Lights",
            "watt_20_Lights",
            "watt_24_Lights",
            "watt_36_Lights",
            "watt_40_Lights",
            "totalWattLights",
            "totalUnits",
        ).order_by("-id")
        results = [
            {
                "areaName": row["areaName"],
                "totalLights": row["totalLights"],
                "18Watt": row["watt_18_Lights"],
                "20Watt": row["watt_20_Lights"],
                "24Watt": row["watt_24_Lights"],
                "36Watt": row["watt_36_Lights"],
                "40Watt": row["watt_40_Lights"],
                "totalWattLights": row["totalWattLights"],
                "totalUnits": row["totalUnits"],
            }
            for row in lights_data
        ]
        return Response({"status": 200, "data": results})


class FansDataApi(APIView):
    # Merged from the colleague's code (54313d5, views/fire_views.py), 2026-11-21:
    # reads only the needed columns with .values(). Same response as before.
    """API view for /api/FansDataApi/ (POST; Login required (default)). Reads FansData. Returns data,
    status.

    Origin: Daksh (merged 2026-11-21 from 54313d5, views/fire_views.py)
    """
    @entryExit
    def post(self, request):
        """POST /api/FansDataApi/. No request fields. Response keys: data, status.

        Origin: Daksh (merged 2026-11-21 from 54313d5, views/fire_views.py)
        """
        fans = (
            FansData.objects.all()
            .order_by("id")
            .values(
                "areaName",
                "totalFans",
                "watt_80_Lights",
                "watt_100_Lights",
                "totalWattFans",
                "totalUnits",
            )
        )
        results = [
            {
                "areaName": f["areaName"],
                "totalFans": f["totalFans"],
                "80watt": f["watt_80_Lights"],
                "100watt": f["watt_100_Lights"],
                "totalWattFans": f["totalWattFans"],
                "totalUnits": f["totalUnits"],
            }
            for f in fans
        ]
        return Response({"status": 200, "data": results})


class avgDataApi(APIView):
    """API view for /api/avgData/ (POST; Login required (default)). Reads AisleGroup, DailySiteReading,
    Site. Takes from_date, siteId, site_id, till_date. Returns energyConsumed, error, status,
    totalDays, value.

    Origin: Ashu (changed from main)
    """
    def post(self, request):
        """POST /api/avgData/. Request fields: from_date, siteId, site_id, till_date. Response keys:
        energyConsumed, error, status, totalDays, value.

        Origin: Ashu (changed from main)
        """
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
