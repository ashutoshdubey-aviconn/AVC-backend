"""Sub-metering charts, trends and snapshot."""

import time
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Case, IntegerField, Max, Sum, When
from django.db.models.functions import TruncMonth
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AisleGroup, DailySiteReading, HourlySiteReading, Site
from wareApp.utility import entryExit, logger


class SubmeteringMonthlyBarChart_new(APIView):
    # Merged from the colleague's code (54313d5, views/metering_views.py), 2026-11-21:
    # one query for all rooms instead of one per room. Same response keys; also
    # finds a room's rows by aisle_group_id or attached_leg_id when leg_id differs.
    """API view for /api/submeterMonthlyTrend_test, /api/submeteringMonthlyBarChart/ (POST; Open: no
    login (AllowAny)). Reads AisleGroup, DailySiteReading, Site. Takes from_date, site_id,
    till_date. Returns Data, Dates, msg, status.

    Origin: Daksh (merged 2026-11-21 from 54313d5, views/metering_views.py)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/submeterMonthlyTrend_test, /api/submeteringMonthlyBarChart/. Request fields:
        from_date, site_id, till_date. Response keys: Data, Dates, msg, status.

        Origin: Daksh (merged 2026-11-21 from 54313d5, views/metering_views.py)
        """
        try:
            data = request.data
            site_id = data.get("site_id", "")
            from_date_str = data.get("from_date", "")
            till_date_str = data.get("till_date", "")

            if not site_id:
                return Response({"status": 400, "msg": "site_id is required"}, status=400)

            # Parse dates
            try:
                from_date = datetime.strptime(from_date_str, "%Y/%m/%d")
                till_date = datetime.strptime(till_date_str, "%Y/%m/%d")
            except (ValueError, TypeError):
                return Response({"status": 400, "msg": "Invalid date format, expected YYYY/MM/DD"}, status=400)

            dates = [(from_date + timedelta(days=x)).strftime("%Y-%m-%d") for x in range((till_date - from_date).days + 1)]

            site = Site.objects.filter(id=site_id).values('live_date').first()
            if not site:
                return Response({"status": 404, "msg": "Site not found"}, status=404)

            live_date = site['live_date']
            if live_date:
                # Handle aware/naive datetime comparison
                live_date_naive = live_date.replace(tzinfo=None) if isinstance(live_date, datetime) else live_date
                from_date_naive = from_date.replace(tzinfo=None)
                if from_date_naive < live_date_naive:
                    from_date = live_date

            # Bulk fetch aisle groups (1 query)
            rooms = list(AisleGroup.objects.filter(site_id=site_id).values('id', 'aisleGroupName', 'attached_leg_id'))

            # Bulk fetch DailySiteReading (1 query)
            readings = DailySiteReading.objects.filter(
                associated_Site_id=site_id,
                reading_for__range=[
                    from_date.date() if isinstance(from_date, datetime) else from_date,
                    till_date.date() if isinstance(till_date, datetime) else till_date
                ],
                is_visible=True
            ).values('leg_id', 'aisle_group_id', 'reading_for', 'unit_consumption')

            # Populate readings in-memory with dual-key mapping for compatibility
            readings_by_room = defaultdict(dict)
            for r in readings:
                if r['reading_for']:
                    date_str = r['reading_for'].strftime("%Y-%m-%d")
                    val = r['unit_consumption'] or 0.0

                    if r['aisle_group_id']:
                        readings_by_room[str(r['aisle_group_id'])][date_str] = val
                    if r['leg_id']:
                        readings_by_room[str(r['leg_id']).strip()][date_str] = val

            dataList = []
            for room in rooms:
                room_id_str = str(room['id'])
                leg_id_str = str(room['attached_leg_id']).strip() if room['attached_leg_id'] else ""

                # Retrieve from map
                room_readings = readings_by_room.get(room_id_str)
                if not room_readings and leg_id_str:
                    room_readings = readings_by_room.get(leg_id_str)

                if not room_readings:
                    room_readings = {}

                new_list = [round(room_readings.get(d, 0.0), 2) for d in dates]
                dataList.append({"name": room['aisleGroupName'], "data": new_list, "type": "column"})

            return Response({"status": 200, "Dates": dates, "Data": dataList}, status=200)

        except Exception as err:
            return Response({"status": 500, "msg": str(err)}, status=500)

class SubmeteringMonthlyBarChart(APIView):
    """API view, not wired to any URL (POST; Login required (default)). Reads AisleGroup,
    DailySiteReading, HourlySiteReading, Site. Takes from_date, site_id, till_date, user_type.
    Returns Data, Dates, result.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST (view not wired to any URL). Request fields: from_date, site_id, till_date, user_type.
        Response keys: Data, Dates, result.

        Origin: Ashu (changed from main)
        """
        t1 = time.time()
        # print("initial time : ", t1)
        data = request.data
        site_id = data.get("site_id", "")
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        logger.debug("%s %s", "site : ", site)
        live_date = site.live_date
        # print("live data", live_date)
        previous_date = live_date - timedelta(days=1)
        # print("previous_date :", previous_date)
        from_date = data.get("from_date", "")
        till_date = data.get("till_date", "")
        user_type = int(data.get("user_type", ""))
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        currentDate = datetime.now()
        dateList = []
        dataList = []
        if tillDate.month == currentDate.month:
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
            for aisle in aisle_group:
                # print("i : ", aisle)
                leg = aisle.attached_leg_id
                # aisle_group = AisleGroup.objects.filter(site_id=site_id, attached_leg_id=leg.leg_id)
                dateList = []
                unitConsumptionList = []
                daily_data = DailySiteReading.objects.filter(
                    associated_Site=site, leg_id=leg, is_visible=True
                )
                for i in range(30):
                    date = tillDate - timedelta(days=29 - i)
                    dateList.append(date.date())
                    unit_consumption = 0.0
                    if currentDate.date() == date.date():
                        # print("current date is ", date)
                        if (
                            site.is_live
                            and user_type in [4, 5]
                            and live_date.date() <= date.date()
                        ) or user_type == 1:
                            hourly = HourlySiteReading.objects.filter(
                                associated_Site=site,
                                leg_id=leg,
                                reading_from__date=date.date(),
                                is_visible=True,
                            )
                            for k in hourly:
                                # print("one entry of hourly", k)
                                unit_consumption += k.unit_consumption
                        unitConsumptionList.append(round(unit_consumption, 2))
                    else:
                        # print("other dates are ", date)
                        if user_type in [4, 5] and previous_date.date() < date.date():
                            # print("inside if")
                            # if (site.is_live and user_type == 4 and live_date.date() <= date.date()) or user_type == 1:
                            daily = daily_data.filter(reading_for=date)
                            # daily = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, reading_for=date, is_visible=True)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                            unitConsumptionList.append(round(unit_consumption, 2))
                        elif user_type == 1:
                            daily = daily_data.filter(reading_for=date)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                            unitConsumptionList.append(round(unit_consumption, 2))
                        else:
                            # print("inside else")
                            unitConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg
                dataList.append(
                    {"name": name, "data": unitConsumptionList, "type": "column"}
                )

        else:
            total_days = (tillDate.day - fromDate.day) + 1
            # all_leg_id = DailySiteReading.objects.filter(associated_Site=site).distinct("leg_id")
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
            for aisle in aisle_group:
                leg = aisle.attached_leg_id
                unitConsumptionList = []
                dateList = []
                daily_data = DailySiteReading.objects.filter(
                    associated_Site=site, leg_id=leg, is_visible=True
                )
                for i in range(0, total_days):
                    date = tillDate - timedelta(days=(total_days - 1) - i)
                    dateList.append(date.date())
                    if user_type in [4, 5] and previous_date.date() < date.date():
                        # print("inside if")
                        daily = daily_data.filter(reading_for=date)
                        # daily = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, reading_for=date, is_visible=True)
                        unit_consumption = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption

                        unitConsumptionList.append(round(unit_consumption, 2))
                    elif user_type == 1:
                        daily = daily_data.filter(reading_for=date)
                        unit_consumption = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption
                        unitConsumptionList.append(round(unit_consumption, 2))
                    else:
                        unitConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg.leg_id
                dataList.append(
                    {"name": name, "data": unitConsumptionList, "type": "column"}
                )
        t2 = time.time()
        return Response({"result": 1, "Dates": dateList, "Data": dataList})


class SubMeteringMonthlyTrendApi(APIView):
    """API view for /api/subMeteringMonthlyTrend/ (POST; Open: no login (AllowAny)). Reads AisleGroup,
    DailySiteReading, Site. Takes site_id. Returns months, msg, result, unit_consumed_avg_data,
    unit_consumed_data.

    Origin: Ashu (changed from main)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/subMeteringMonthlyTrend/. Request fields: site_id. Response keys: months, msg,
        result, unit_consumed_avg_data, unit_consumed_data.

        Origin: Ashu (changed from main)
        """
        data = request.data
        site_id = data.get("site_id", "")
        # user_type = data.get("user_type") # Not used

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"result": 0, "msg": "Site not found"})

        # Date Setup
        today_date = datetime.now()
        current_date = today_date.replace(day=15)
        live_date = site.live_date.date()

        # Original logic used strictly 'previous_date' (yesterday) as end bound
        previous_date = today_date - timedelta(days=1)

        # Calculate the 12-month window
        generated_months = []
        month_list_str = []

        for i in range(11, -1, -1):
            m = current_date - timedelta(days=int(i * 365 / 12))
            generated_months.append(m)

            date_in_str = m.strftime("%b")
            year_in_str = m.strftime("%Y")
            modified_date = date_in_str + "-" + year_in_str
            month_list_str.append(modified_date)

        final_data = []
        avg_data = []  # Empty as per original

        if site:
            # 1. Fetch Per-Leg Data Grouped by Month (Optimized)
            # Filter efficiently by date range and site
            # We fetch a wider range to catch all possible data, then align in Python to match original logic

            leg_data_qs = (
                DailySiteReading.objects.filter(
                    associated_Site=site,
                    is_visible=True,
                    reading_for__gte=live_date,
                    reading_for__lte=previous_date,
                )
                .annotate(month=TruncMonth("reading_for"))
                .values("leg_id", "month")
                .annotate(total_consumption=Sum("unit_consumption"))
            )

            # Dictionary for O(1) Lookup: (leg_id, year, month) -> sum
            leg_data_map = {}
            for entry in leg_data_qs:
                d = entry["month"]
                if d:
                    key = (entry["leg_id"], d.year, d.month)
                    leg_data_map[key] = entry["total_consumption"] or 0

            # 2. Build Response for Each Aisle
            aisle_group = AisleGroup.objects.filter(site_id=site_id)

            for aisle in aisle_group:
                name_id = aisle.attached_leg_id
                aisle_name = aisle.aisleGroupName
                energy_consumed_list = []

                for m in generated_months:
                    # Logic: if month is outside [live_date, previous_date], it won't be in map
                    # (due to query filter) or will be 0.
                    val = leg_data_map.get((name_id, m.year, m.month), 0)
                    energy_consumed_list.append(round(val, 1))

                final_data.append(
                    {"name": aisle_name, "data": energy_consumed_list, "type": "column"}
                )

            # 3. Fetch Site Totals for ExpectedMonthlyUnits (Optimized)
            site_data_qs = (
                DailySiteReading.objects.filter(
                    associated_Site=site,
                    is_visible=True,
                    reading_for__gte=live_date,
                    reading_for__lte=previous_date,
                )
                .annotate(month=TruncMonth("reading_for"))
                .values("month")
                .annotate(total_consumption=Sum("unit_consumption"))
            )

            site_data_map = {}
            for entry in site_data_qs:
                d = entry["month"]
                if d:
                    site_data_map[(d.year, d.month)] = entry["total_consumption"] or 0

            # Calculate Running Average
            total_monthly_avg_data = 0
            total_site_live_month = 0
            monthly_avg_site_level_list = []

            for m in generated_months:
                monthly_avg_site_level = site_data_map.get((m.year, m.month))
                monthly_avg = 0

                # Logic matching original:
                # 1. Match Live Date Month (Reset/Start)
                if m.year == live_date.year and m.month == live_date.month:
                    val = monthly_avg_site_level or 0
                    monthly_avg = val
                    total_site_live_month += 1
                    total_monthly_avg_data += val

                # 2. Before Live Date (implicit check)
                elif monthly_avg_site_level is None and (
                    m.year < live_date.year
                    or (m.year == live_date.year and m.month < live_date.month)
                ):
                    monthly_avg = 0

                # 3. After Live Date
                else:
                    val = monthly_avg_site_level or 0
                    total_site_live_month += 1
                    total_monthly_avg_data += val
                    if total_site_live_month > 0:
                        monthly_avg = total_monthly_avg_data / total_site_live_month
                    else:
                        monthly_avg = 0

                monthly_avg_site_level_list.append(round(monthly_avg, 1))

            final_data.append(
                {
                    "yAxis": 1,
                    "name": "ExpectedMonthlyUnits",
                    "data": monthly_avg_site_level_list,
                    "type": "spline",
                }
            )

        return Response(
            {
                "result": 1,
                "months": month_list_str,
                "unit_consumed_data": final_data,
                "unit_consumed_avg_data": avg_data,
            }
        )


class SubmeteringSnapshotAPI(APIView):
    # Merged from the colleague's code (54313d5, views/site_views.py), 2026-11-21:
    # totals with one SUM query instead of a Python loop; a site without live_date
    # no longer fails. Same response keys.
    """API view for /api/submeteringSnapshot/ (POST; Open: no login (AllowAny)). Reads AisleGroup,
    DailySiteReading, Site. Takes site_id. Returns alarms, current_date, dailyAvg, energy_consumed,
    error, firstmnthDate, live_date, monthlyAvg, msg, status.

    Origin: Daksh (merged 2026-11-21 from 54313d5, views/site_views.py)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """POST /api/submeteringSnapshot/. Request fields: site_id. Response keys: alarms,
        current_date, dailyAvg, energy_consumed, error, firstmnthDate, live_date, monthlyAvg, msg,
        status.

        Origin: Daksh (merged 2026-11-21 from 54313d5, views/site_views.py)
        """
        try:
            data = request.data
            site_id = data.get('site_id')
            if not site_id:
                return Response({'error': 'Site ID required'}, status=status.HTTP_400_BAD_REQUEST)

            site = Site.objects.filter(id=site_id).values('live_date').first()
            if not site:
                return Response({'error': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)

            live_date = site['live_date']
            if not live_date:
                # Fallback if live_date is not set
                live_date = datetime.now()

            current_date = datetime.now()
            firstdate = current_date.replace(day=1)
            firstmnthDate = firstdate.strftime("%Y-%m-%d")
            fromDate = live_date.strftime("%Y-%m-%d")

            previous_date = current_date - timedelta(days=1)
            tillDate = previous_date.strftime("%Y-%m-%d")

            # Days count calculation
            if isinstance(live_date, datetime):
                days = (current_date - live_date)
            else:
                days = (current_date.date() - live_date)
            totaldays = max(days.days + 1, 1)

            # Get leg IDs for the site
            leg_ids = list(AisleGroup.objects.filter(site_id=site_id).values_list('attached_leg_id', flat=True))

            # Bulk sum energy consumed from live date to yesterday
            daily_agg = DailySiteReading.objects.filter(
                associated_Site_id=site_id,
                leg_id__in=leg_ids,
                reading_for__gte=fromDate,
                reading_for__lte=tillDate
            ).aggregate(total_energy=Sum('unit_consumption'))
            energyConsumed = daily_agg['total_energy'] or 0.0

            avgData = round(energyConsumed / totaldays, 2)

            # Bulk sum monthly consumed energy
            monthly_agg = DailySiteReading.objects.filter(
                associated_Site_id=site_id,
                leg_id__in=leg_ids,
                reading_for__gte=firstmnthDate,
                reading_for__lte=tillDate
            ).aggregate(total_energy=Sum('unit_consumption'))
            unit_consumed = monthly_agg['total_energy'] or 0.0

            return Response({
                "status": 200,
                "alarms": 0,
                "energy_consumed": round(energyConsumed, 2),
                "dailyAvg": avgData,
                "monthlyAvg": round(unit_consumed, 2),
                "firstmnthDate": firstmnthDate,
                "current_date": tillDate,
                "live_date": fromDate
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e), "status": 0, 'msg': 'Data Not Present'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SubmeteringHourlyBarChart(APIView):
    """API view, not wired to any URL (POST; Login required (default)). Reads AisleGroup,
    DailySiteReading, HourlySiteReading, Site. Takes date, site_id. Returns Data, Hours, result.

    Origin: Ashu (changed from main)
    """
    @entryExit
    def post(self, request):
        """POST (view not wired to any URL). Request fields: date, site_id. Response keys: Data, Hours,
        result.

        Origin: Ashu (changed from main)
        """
        data = request.data
        # return Response({"status":201, "msg":"testing","data":data})
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        logger.debug("%s %s", "function start time is : ", start_time)
        site = Site.objects.get(id=site_id)
        # return Response({"status":200, "msg":"working fine"})
        date = data.get("date", "")
        date = datetime.strptime(date, "%Y/%m/%d")
        logger.debug("%s %s", "date ::", date)
        logger.debug("%s %s", "ii", date.date())
        hourList = []
        dataList = []
        all_leg_id = DailySiteReading.objects.filter(
            associated_Site=site, reading_for=date.date()
        ).distinct("leg_id")
        oneDayData = HourlySiteReading.objects.filter(
            associated_Site=site_id, reading_from__date=date.date(), is_visible=True
        )
        logger.debug("%s", "@@@@@@@@@@@@@@")
        for leg in all_leg_id:
            aisle_name = AisleGroup.objects.filter(
                site=site_id, attached_leg_id=leg.leg_id
            )
            if aisle_name.exists():
                name = aisle_name[0].aisleGroupName
            else:
                name = leg.leg_id
            logger.debug("%s %s", "leg :", leg)
            unitConsumptionList = []
            savingConsumptionList = []
            hourList = []
            for i in range(24):
                current_hour = i
                logger.debug("%s %s", "current_hour", current_hour)
                if current_hour <= 9:
                    hr = "0" + str(current_hour) + ":00"
                else:
                    hr = str(current_hour) + ":00"
                hourList.append(hr)
                unit_consumption = 0.0
                energy_saved = 0.0
                if aisle_name.exists():
                    hourly = oneDayData.filter(
                        aisle_group=aisle_name[0], reading_from__hour=current_hour
                    )
                else:
                    hourly = oneDayData.filter(
                        leg_id=leg, reading_from__hour=current_hour
                    )
                logger.debug("%s %s", "hourly data", hourly)
                if hourly.exists():
                    for j in hourly:
                        try:
                            unit_consumption += j.unit_consumption
                        except Exception as e:
                            logger.debug("%s %s", "exception", e)
                unitConsumptionList.append(round(unit_consumption, 2))
            logger.debug("%s %s", "unit data: ", unitConsumptionList)
            dataList.append(
                {"name": name, "data": unitConsumptionList, "type": "column"}
            )
        end_time = datetime.now()
        logger.debug("%s %s", "function end time is : ", end_time)
        time_taken = end_time - start_time
        logger.debug("%s %s", "time_taken", time_taken)
        hourList = [
            "00:00",
            "01:00",
            "02:00",
            "03:00",
            "04:00",
            "05:00",
            "06:00",
            "07:00",
            "08:00",
            "09:00",
            "10:00",
            "11:00",
            "12:00",
            "13:00",
            "14:00",
            "15:00",
            "16:00",
            "17:00",
            "18:00",
            "19:00",
            "20:00",
            "21:00",
            "22:00",
            "23:00",
        ]
        return Response({"result": 1, "Hours": hourList, "Data": dataList})


class SubmeteringHourlyBarChartNew(APIView):

    """API view for /api/submeteringHourlyData/ (POST; Login required (default)). Reads AisleGroup,
    DailySiteReading, HourlySiteReading, Site. Takes date, site_id. Returns Data, Hours, result.

    Origin: Ashu
    """
    @entryExit
    def post(self, request):
        """POST /api/submeteringHourlyData/. Request fields: date, site_id. Response keys: Data, Hours,
        result.

        Origin: Ashu
        """
        start_time = datetime.now()
        from collections import defaultdict

        from django.db.models.functions import ExtractHour

        data = request.data
        site_id = data.get("site_id")
        date = datetime.strptime(data.get("date"), "%Y/%m/%d").date()
        logger.debug("%s %s", "######################", datetime.now())
        site = Site.objects.get(id=site_id)
        logger.debug("%s %s", "site: ", site)
        # Fixed hour list
        hour_list = [f"{str(i).zfill(2)}:00" for i in range(24)]
        # print("hour_list: ", hour_list)
        # -------------------------
        # Fetch leg IDs
        # -------------------------
        legs = (
            DailySiteReading.objects.filter(associated_Site=site, reading_for=date)
            .values_list("leg_id", flat=True)
            .distinct()
        )
        # print("legs: ", legs)

        # -------------------------
        # Fetch aisle mappings
        # -------------------------
        aisle_map = {
            ag.attached_leg_id: ag
            for ag in AisleGroup.objects.filter(site=site_id, attached_leg_id__in=legs)
        }
        logger.debug("%s %s", "aisle group: ", datetime.now())

        # -------------------------
        # Fetch & aggregate hourly data in ONE QUERY
        # -------------------------
        hourly_data = (
            HourlySiteReading.objects.filter(
                associated_Site=site_id, reading_from__date=date, is_visible=True
            )
            .annotate(hour=ExtractHour("reading_from"))
            .values("leg_id", "aisle_group", "hour")
            .annotate(
                total=Sum("unit_consumption"),
                # 1 when a catch-up spread filled the hour (is_estimated).
                estimated=Max(Case(When(is_estimated=True, then=1), default=0, output_field=IntegerField())),
            )
        )
        logger.debug("%s %s", "hourly data: ", datetime.now())

        # -------------------------
        # Build lookup dict
        # -------------------------
        data_lookup = defaultdict(lambda: defaultdict(float))
        estimated_lookup = defaultdict(set)

        for row in hourly_data:
            key = row["aisle_group"] or row["leg_id"]
            data_lookup[key][row["hour"]] += row["total"] or 0.0
            if row["estimated"]:
                estimated_lookup[key].add(row["hour"])

        # -------------------------
        # Build response data
        # -------------------------
        data_list = []

        for leg_id in legs:
            aisle = aisle_map.get(leg_id)
            key = aisle.id if aisle else leg_id
            name = aisle.aisleGroupName if aisle else leg_id

            hourly_values = [
                round(data_lookup[key].get(hour, 0.0), 2) for hour in range(24)
            ]

            data_list.append({
                "name": name, "data": hourly_values, "type": "column",
                "estimated": [hour in estimated_lookup[key] for hour in range(24)],
            })

        end_time = datetime.now()
        logger.debug("%s %s", "Time taken:", end_time - start_time)

        return Response({"result": 1, "Hours": hour_list, "Data": data_list})


class NewSubMeteringMonthlyTrendApi(APIView):
    """API view for /api/newSubMeteringMonthlyTrend/ (POST; Open: no login (AllowAny)). Reads
    AisleGroup, DailySiteReading, Site. Takes site_id, user_type. Returns months, result,
    unit_consumed_avg_data, unit_consumed_data.

    Origin: Ashu (changed from main)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/newSubMeteringMonthlyTrend/. Request fields: site_id, user_type. Response keys:
        months, result, unit_consumed_avg_data, unit_consumed_data.

        Origin: Ashu (changed from main)
        """
        import calendar

        data = request.data
        site_id = data.get("site_id", "")
        user_type = data.get("user_type")
        current_date = datetime.now().replace(day=15)
        site = Site.objects.get(id=site_id)
        current = datetime.now()
        live_date = site.live_date.date()
        liveDate = datetime.strftime(live_date, "%Y-%m-%d")
        previous_date = current - timedelta(days=1)
        logger.debug("%s %s", "previous_date", previous_date)
        previousDate = datetime.strftime(previous_date, "%Y-%m-%d")
        previous_month_year = live_date.strftime("%Y-%m")
        logger.debug("%s %s", "previous_month_year", previous_month_year)
        today_date = datetime.now()
        current = today_date - timedelta(days=1)
        month_list = []
        final_data = []  # Initialize outside the site check
        avg_data = []
        if site:
            aisle_group = AisleGroup.objects.filter(site_id=site_id)
            for aisle in aisle_group:
                logger.debug("%s %s", "All legs", aisle)
                name = aisle.attached_leg_id
                aisleName = aisle.aisleGroupName
                energy_consumed_list = []
                avg_consumed_list = []
                for i in range(11, -1, -1):
                    month = current_date - timedelta(
                        days=int(i * 365 / 12)
                    )  # Cast the division result to int
                    logger.debug("%s %s", "month%%%%", month)
                    logger.debug("%s %s", "month##### : ", month.date())
                    date_in_str = month.strftime("%b")
                    year_in_str = month.strftime("%Y")
                    modified_date = date_in_str + "-" + year_in_str
                    month_list.append(modified_date)
                    month_year = month.strftime("%Y-%m")
                    logger.debug("%s %s", "month_year", month_year)
                    daily = DailySiteReading.objects.filter(
                        associated_Site=site,
                        leg_id=name,
                        reading_for__year=month.year,
                        reading_for__gte=liveDate,
                        reading_for__lte=previousDate,
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum("unit_consumption"))
                    logger.debug("%s", daily)
                    unit_consumed = daily["unit_consumption__sum"]
                    # avg_unit_consumed = daily["unit_consumption__avg"]
                    if unit_consumed is None:
                        unit_consumed = 0
                    # if avg_unit_consumed is None:
                    #     avg_unit_consumed = 0
                    logger.debug("%s", unit_consumed)
                    energy_consumed_list.append(round(unit_consumed, 1))
                    # avg_consumed_list.append(round(avg_unit_consumed, 1))
                final_data.append(
                    {"name": aisleName, "data": energy_consumed_list, "type": "column"}
                )
                # avg_data.append({"name": aisleName, "data": avg_consumed_list, "type": "spline"})

            # to calculate avg on site level
            total_monthly_avg_data = 0
            total_site_live_month = 0
            monthly_avg_site_level_list = []
            for i in range(11, -1, -1):
                month = current_date - timedelta(
                    days=int(i * 365 / 12)
                )  # Cast the division result to int
                logger.debug("%s %s", "month%%%%", month)
                logger.debug("%s %s", "month##### : ", month.date())
                date_in_str = month.strftime("%b")
                year_in_str = month.strftime("%Y")
                modified_date = date_in_str + "-" + year_in_str
                month_list.append(modified_date)
                month_year = month.strftime("%Y-%m")
                logger.debug("%s %s", "month_year", month_year)
                if month.month == live_date.month and month.year == live_date.year:
                    monthly = DailySiteReading.objects.filter(
                        associated_Site=site,
                        reading_for__year=month.year,
                        reading_for__gte=liveDate,
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum("unit_consumption"))
                    monthly_avg_site_level = monthly["unit_consumption__sum"]
                    logger.debug(
                        "%s %s %s",
                        "month: {}".format(month),
                        " data: ",
                        monthly_avg_site_level,
                    )
                elif month.month == today_date.month and month.year == today_date.year:
                    monthly = DailySiteReading.objects.filter(
                        associated_Site=site,
                        reading_for__year=month.year,
                        reading_for__lt=today_date.date(),
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum("unit_consumption"))
                    monthly_avg_site_level = monthly["unit_consumption__sum"]
                    logger.debug(
                        "%s %s %s",
                        "month: {}".format(month),
                        " data: ",
                        monthly_avg_site_level,
                    )
                else:
                    monthly = DailySiteReading.objects.filter(
                        associated_Site=site,
                        reading_for__year=month.year,
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum("unit_consumption"))
                    monthly_avg_site_level = monthly["unit_consumption__sum"]
                    logger.debug(
                        "%s %s %s",
                        "month: {}".format(month),
                        " data: ",
                        monthly_avg_site_level,
                    )
                # total_monthly_avg_data += monthly_avg_site_level
                if (
                    month.month == live_date.month and month.year == live_date.year
                ):  # live date month data
                    try:

                        total_days_in_month = calendar.monthrange(
                            month.year, month.month
                        )[1]
                        diff_from_live_date = total_days_in_month - live_date.day + 1
                        monthly_avg_site_level = (
                            monthly_avg_site_level / diff_from_live_date
                        ) * total_days_in_month
                        monthly_avg = monthly_avg_site_level

                        # total_site_live_month += 1
                        # total_monthly_avg_data += monthly_avg_site_level
                    except Exception:
                        monthly_avg = 0
                elif monthly_avg_site_level is None:  # before live date month data
                    monthly_avg = 0
                else:  # after live month data
                    # total_site_live_month += 1

                    # total_monthly_avg_data += monthly_avg_site_level
                    # monthly_avg = total_monthly_avg_data / total_site_live_month
                    if (
                        month.month == today_date.month
                        and month.year == today_date.year
                    ):
                        total_days_in_month = calendar.monthrange(
                            month.year, month.month
                        )[1]
                        total_days = today_date.day - 1
                        monthly_avg = (
                            monthly_avg_site_level / total_days
                        ) * total_days_in_month
                        # avg_data.append({"tm":total_days_in_month, "td": total_days, "avg":monthly_avg, "month": month.day, "tdate":today_date})
                    else:
                        monthly_avg = monthly_avg_site_level
                monthly_avg_site_level_list.append(round(monthly_avg, 1))
            final_data.append(
                {
                    "yAxis": 1,
                    "name": "ExpectedMonthlyUnits",
                    "data": monthly_avg_site_level_list,
                    "type": "spline",
                }
            )

        return Response(
            {
                "result": 1,
                "months": month_list,
                "unit_consumed_data": final_data,
                "unit_consumed_avg_data": avg_data,
            }
        )
