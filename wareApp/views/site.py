"""Site-level pages: consumption graphs, live load, phase data and site info."""

from collections import defaultdict
from datetime import datetime, timedelta

from django.views.decorators.csrf import csrf_exempt
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    DailySiteReading,
    HourlySiteReading,
    Site,
    SiteLoadPower,
)
from wareApp.serializers import SiteSerializer
from wareApp.utility import entryExit, logger


class SiteTotalGraphDataDaily(APIView):

    def post(self, request):
        from django.core.cache import cache

        data = request.data
        till_date = data.get("till_date", "")
        from_date = data.get("from_date", "")
        logger.debug("%s %s", "from date: ", from_date)
        site_id = data.get("site_id", " ")
        logger.debug("%s %s", "This is the site id: ", site_id)
        site = Site.objects.get(id=int(site_id))
        logger.debug("%s %s", "site: ", site)
        try:
            from_date = datetime.strptime(from_date, "%Y/%m/%d")
            till_date = datetime.strptime(till_date, "%Y/%m/%d")

            # Optimization & Caching START
            data = []

            # 1. Calculate Date Range (Caps at 31 days)
            max_days = 31
            actual_days = (till_date - from_date).days + 1
            days_to_process = min(actual_days, max_days)

            dates_obj_list = [
                from_date.date() + timedelta(days=i) for i in range(days_to_process)
            ]
            dates = dates_obj_list  # for response

            if not dates_obj_list:
                return Response(
                    {"Dates": [], "Data": [], "status": "1", "msg": "No Data"}
                )

            start_date_obj = dates_obj_list[0]
            end_date_obj = dates_obj_list[-1]

            # 2. Fetch all unique legs for the site (to preserve list of series even if empty)
            legs = (
                DailySiteReading.objects.filter(associated_Site=site)
                .values_list("leg_id", flat=True)
                .distinct()
            )

            # 3. Fetch Readings with Monthly Caching Strategy
            readings_map = defaultdict(dict)
            current_date = datetime.now().date()

            # Helper to generate month ranges
            month_ranges = []
            curr = start_date_obj
            while curr <= end_date_obj:
                # End of current month
                if curr.month == 12:
                    next_month = curr.replace(year=curr.year + 1, month=1, day=1)
                else:
                    next_month = curr.replace(month=curr.month + 1, day=1)

                month_end = next_month - timedelta(days=1)
                segment_end = min(month_end, end_date_obj)

                month_ranges.append((curr, segment_end))
                curr = next_month

            for m_start, m_end in month_ranges:
                is_past_month = (m_start.year < current_date.year) or (
                    m_start.year == current_date.year
                    and m_start.month < current_date.month
                )

                if is_past_month:
                    cache_key = f"SITE_{site.id}_DAILY_READINGS_V1_{m_start.year}_{m_start.month}"
                    # cached_month_data = cache.get(cache_key)
                    cached_month_data = None

                    if cached_month_data is None:
                        # Fetch entire month data for cache consistency
                        full_month_start = m_start.replace(day=1)
                        if full_month_start.month == 12:
                            full_month_next = full_month_start.replace(
                                year=full_month_start.year + 1, month=1, day=1
                            )
                        else:
                            full_month_next = full_month_start.replace(
                                month=full_month_start.month + 1, day=1
                            )
                        full_month_end = full_month_next - timedelta(days=1)

                        month_readings = DailySiteReading.objects.filter(
                            associated_Site=site,
                            reading_for__range=[full_month_start, full_month_end],
                        ).values("leg_id", "reading_for", "unit_consumption")

                        cached_month_data = defaultdict(dict)
                        for r in month_readings:
                            cached_month_data[r["leg_id"]][r["reading_for"]] = r[
                                "unit_consumption"
                            ]

                        # Cache for 24 hours (86400 seconds)
                        # cache.set(cache_key, cached_month_data, timeout=86400)

                    # Merge cached data relevant to requested range into main map
                    for leg, dates_data in cached_month_data.items():
                        for d_key, val in dates_data.items():
                            if m_start <= d_key <= m_end:
                                readings_map[leg][d_key] = val

                else:
                    # Current/Future month: Fetch fresh (only requested range to be efficient)
                    fresh_readings = DailySiteReading.objects.filter(
                        associated_Site=site, reading_for__range=[m_start, m_end]
                    ).values("leg_id", "reading_for", "unit_consumption")

                    for r in fresh_readings:
                        readings_map[r["leg_id"]][r["reading_for"]] = r[
                            "unit_consumption"
                        ]

            # 4. Bulk fetch AisleGroup Names
            name_map = {}
            try:
                aisle_groups = AisleGroup.objects.filter(
                    attached_leg_id__in=legs
                ).values("attached_leg_id", "aisleGroupName")
                name_map = {
                    item["attached_leg_id"]: item["aisleGroupName"]
                    for item in aisle_groups
                }
            except Exception as e:
                logger.debug("%s %s", "Error calculating names:", e)

            # 5. Construct Data
            for leg_id in legs:
                daily_consumption = []
                for d in dates_obj_list:
                    # Get consumption from map, default to 0
                    val = readings_map.get(leg_id, {}).get(d, 0)
                    daily_consumption.append(round(val, 2))

                # Get name from map, default to leg_id
                aisle_group_name = name_map.get(leg_id, str(leg_id))

                singleData = {"name": aisle_group_name, "data": daily_consumption}
                data.append(singleData)

            response = {
                "Dates": dates,
                "Data": data,
                "status": "1",
                "msg": "Data Present",
            }
            logger.debug("%s %s", "response :", response)

            return Response(response)

        except Exception as e:
            logger.debug("%s %s", "exception is ", e)
            import traceback

            traceback.print_exc()
            return Response({"error": str(e)})


class SiteTotalGraphDataHourly(APIView):

    def post(self, request):
        data = request.data
        date = data.get("date", "")
        logger.debug("%s %s", "input date: ", date)
        date = datetime.strptime(date, "%Y/%m/%d")
        site_id = data.get("site_id", " ")
        logger.debug("%s %s", "This is the site id: ", site_id)
        site = Site.objects.get(id=site_id)
        logger.debug("%s %s", "site: ", site)
        try:
            data = []
            hours = []
            for leg in DailySiteReading.objects.distinct("leg_id").filter(
                associated_Site=site
            ):
                logger.debug("%s %s", "leg id is:", leg)
                hourly_consumption = []
                hours = []

                for i in range(24):
                    hr = date.hour + i
                    if hr <= 9:
                        hr = "0" + str(hr) + ":00"
                    else:
                        hr = str(hr) + ":00"
                    hours.append(hr)
                    hour = date.replace(hour=i)
                    logger.debug("%s %s", "hour :", hour)
                    hours_graph_data = HourlySiteReading.objects.filter(
                        associated_Site=site, leg_id=leg, reading_from=hour
                    )
                    logger.debug("%s %s", "hours_graph_data", hours_graph_data)
                    if hours_graph_data.exists():
                        one_hour_consumption = round(
                            hours_graph_data[0].unit_consumption, 2
                        )
                        logger.debug(
                            "%s %s", "one_hour_consumption", one_hour_consumption
                        )
                    else:
                        one_hour_consumption = 0.0
                    hourly_consumption.append(one_hour_consumption)
                if AisleGroup.objects.filter(attached_leg_id=leg).exists():
                    aisle_group = AisleGroup.objects.get(
                        attached_leg_id=leg
                    ).aisleGroupName
                else:
                    aisle_group = str(leg)
                singleData = {"name": aisle_group, "data": hourly_consumption}
                data.append(singleData)

            response = {
                "Hours": hours,
                "Data": data,
                "status": "1",
                "msg": "Data Present",
            }
            logger.debug("%s %s", "response :", response)

            return Response(response)

        except Exception as e:
            logger.debug("%s %s", "exception is ", e)
            return Response({"error": "errorrrrrrrrrrrrrrrrr"})


class SiteTotalGraphDataHourlyWHTM(APIView):
    def post(self, request):
        data = request.data
        date, site_id = data.get("date", ""), data.get("site_id", "")
        date = datetime.strptime(date, "%Y/%m/%d")
        try:
            hourlyData, hours = [], ["{:02d}:00".format(i) for i in range(24)]
            rooms = list(
                reversed(
                    list(
                        AisleGroup.objects.filter(site=site_id).values_list(
                            "attached_leg_id", flat=True
                        )
                    )
                )
            )
            for i in rooms:
                cons = list(
                    HourlySiteReading.objects.filter(
                        associated_Site=site_id, leg_id=i, reading_from__date=date
                    )
                    .order_by("reading_from__hour")
                    .values_list("unit_consumption", flat=True)
                )
                cons.extend([0] * (24 - len(cons)))
                hourlyData.append(
                    {
                        "name": (
                            AisleGroup.objects.get(attached_leg_id=i).aisleGroupName
                            if AisleGroup.objects.filter(attached_leg_id=i).exists()
                            else i
                        ),
                        "data": [round(j, 2) for j in cons],
                    }
                )
            return Response(
                {"status": 1, "Hours": hours, "Data": hourlyData, "msg": "Data Present"}
            )

        except Exception as e:
            return Response({"error": e.args, "status": 0, "msg": "Data Not Present"})


class SiteCurrentLoadInfo(APIView):

    def post(self, request):

        data = request.data
        site_id = data.get("site_id")
        load_value = r_current = y_current = b_current = 0
        r_volt = y_volt = b_volt = max_load = min_load = 0
        r_power_factor = y_power_factor = b_power_factor = 0.0
        power_supply = status = ""

        # print(site_id)
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            active_power_sources = SiteLoadPower.objects.filter(
                Associated_Site=int(site_id), Status="ON"
            )
            for i in active_power_sources:
                power_load = i.Site_Total_Load
                power_load = power_load / 1000
                value = power_load
                load_value += value

                r_volt = int(round(i.r_volt, 0))
                y_volt = int(round(i.y_volt, 0))
                b_volt = int(round(i.b_volt, 0))
                r_current += int(i.r_current)
                y_current += int(i.y_current)
                b_current += int(i.b_current)
                r_power_factor = i.r_power_factor
                y_power_factor = i.y_power_factor
                b_power_factor = i.b_power_factor
                max_load = round(i.max_load / 1000, 3)
                min_load = round(i.min_load / 1000, 3)
                power_supply = i.Supply_Source
                status = i.Status

            return Response(
                {
                    "Total_Load": str(round(load_value, 3)),
                    "R_Voltage": str(r_volt),
                    "Y_Voltage": str(y_volt),
                    "B_Voltage": str(b_volt),
                    "R_Current": str(round(r_current, 0)),
                    "Y_Current": str(round(y_current, 0)),
                    "B_Current": str(round(b_current, 0)),
                    "R_Power_Factor": str(round(r_power_factor, 3)),
                    "Y_Power_Factor": str(round(y_power_factor, 3)),
                    "B_Power_Factor": str(round(b_power_factor, 3)),
                    "max_load": str(max_load),
                    "min_load": str(min_load),
                    "Power_supply": power_supply,
                    "Status": status,
                }
            )

        except Exception as e:
            logger.debug("%s %s", "This is exception ", e)
            return Response({"status": 500, "error": "ERROR", "msg": str(e)})


class SitePhaseVoltagesInfo(APIView):

    def post(self, request, *args, **kwargs):
        data = request.data
        site_id = data.get("site_id")
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            if True:  # Token.objects.filter(key=token_key) :
                r_volt = InstantenousPhaseVoltage.objects.filter(
                    Assocted_Site=int(site_id)
                )[0].r_volt
                y_volt = InstantenousPhaseVoltage.objects.filter(
                    Assocaited_Site=int(site_id)
                )[0].y_volt
                b_volt = InstantenousPhaseVoltage.objects.filter(
                    Assocaited_Site=int(site_id)
                )[0].b_volt
                return Response(
                    {
                        "R-phase Voltage": str(r_volt),
                        "Y-phase Voltage": str(y_volt),
                        "B-phase Voltage": str(b_volt),
                    }
                )

            else:
                logger.debug("%s", "This session key is not valid.")
                return Response({"Error": "This session key is not valid."})

        except Exception as e:
            logger.debug("%s %s", "This is exception ", e)
            return Response({"Error": "EXCEPTION"})


class SitePhaseCurrentsInfo(APIView):

    def post(self, request, *args, **kwargs):
        data = request.data
        site_id = data.get("site_id")
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            if True:  # Token.objects.filter(key=token_key) :
                r_current = InstantenousPhaseCurrent.objects.filter(
                    Assocaited_Site=int(site_id)
                )[0].r_current
                y_current = InstantenousPhaseCurrent.objects.filter(
                    Assocaited_Site=int(site_id)
                )[0].y_current
                b_current = InstantenousPhaseCurrent.objects.filter(
                    Assocaited_Site=int(site_id)
                )[0].b_current
                return Response(
                    {
                        "R-phase Current": str(r_current),
                        "Y-phase Current": str(y_current),
                        "B-phase Current": str(b_current),
                    }
                )

            else:
                logger.debug("%s", "This session key is not valid.")

        except Exception as e:
            logger.debug("%s %s", "This is exception ", e)


class PowerSupplyInfo(APIView):

    def post(self):
        data = self.request
        site_id = data.site_id(
            "site_id",
        )
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            if True:  # Token.objects.filter(key=token_key) :
                power_supply = PowerSupplyStatus.objects.filter(
                    Associated_Site=site_id
                )[0].Supply_Source
                return Response({"Power_supply": power_supply})

            else:
                logger.debug("%s", "This session key is not valid.")

        except Exception as e:
            logger.debug("%s %s", "This is exception ", e)


class SiteInfo(APIView):
    @csrf_exempt
    @entryExit
    def post(self, request):  # post method should be used
        data = request.data
        logger.debug("%s %s", "This is the site data", data)
        id = data["siteId"]
        site = Site.objects.get(id=id)
        serializer_class = SiteSerializer(site)
        return Response({"site": serializer_class.data})


class HourlySiteReadingForOneSite(APIView):

    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        logger.debug("%s %s %s", "siteId", site_id, type(site_id))
        site = Site.objects.get(id=int(site_id))
        date = data.get("date", "")
        logger.debug("%s %s", "received date", date)
        date_now = datetime.strptime(date, "%Y/%m/%d")
        logger.debug("%s %s", "converted date in date format", date_now)
        totalData = []
        all_leg_id = HourlySiteReading.objects.distinct("leg_id").filter(
            associated_Site=site
        )
        logger.debug("%s %s", "all leg id object", all_leg_id)
        for i in all_leg_id:
            oneLegDataList = []
            for j in range(0, 23):
                unit_consumption = 0.0
                hour = date_now + timedelta(hours=j)
                logger.debug("%s %s", "hour : ", hour.hour)
                hourly = HourlySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id=i.leg_id,
                    reading_from__date=date_now.date(),
                    reading_from__hour=hour.hour,
                )

                for k in hourly:
                    unit_consumption += k.unit_consumption
                logger.debug(
                    "%s %s %s %s",
                    "hour is :",
                    hour,
                    "consumption of this hour is : ",
                    unit_consumption,
                )
                oneLegDataList.append(
                    {"hour": hour.hour, "consumption": unit_consumption}
                )
            totalData.append({"legId": i.leg_id, "legData": oneLegDataList})
        return Response({"result": 1, "data": totalData})


class DemoApi(APIView):
    @entryExit
    def get(self, request):
        data = request.data
        my_list = []
        daily = DailySiteReading.objects.filter(associated_Site=1)
        for i in daily:
            my_list.append(
                {
                    "consumption": i.unit_consumption,
                    "saving": i.energy_saved,
                    "date": i.reading_for,
                }
            )
        return Response({"result": 1, "data": my_list})


class TotalAlarmsOnSitePageTabularForm(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data in alarm table", data)
        site_id = data.get("site_id", "")
        logger.debug("%s %s", "site did ", site_id)
        site = Site.objects.get(id=site_id)
        logger.debug("%s %s", "site details ", site)
        customer = site.customer
        alarms = AlarmNotifications.objects.filter(
            created_by=customer, site_id=site, user_level=4
        )
        logger.debug("%s %s", "alarms: ", alarms)
        data_list = []
        for i in alarms:
            logger.debug("%s %s", "inside the loop!!", i)
            alarm_type = i.get_Alarm_type_display()
            logger.debug("%s %s", "alarm type: ", alarm_type)
            object_type = i.get_object_type_display()
            logger.debug("%s %s", "object type: ", object_type)
            object_name = i.object_id
            logger.debug("%s %s", "object name: ", object_name)
            created_time = i.created_time
            logger.debug("%s %s", "created time: ", created_time)
            created_time = datetime.strftime(created_time, "%d-%m-%Y")
            alarm_priority = i.get_Alarm_priority_display()
            logger.debug("%s %s", "alarm priority: ", alarm_priority)
            data_list.append(
                {
                    "alarm_type": alarm_type,
                    "object_type": object_type,
                    "object_name": object_name,
                    "alarm_priority": alarm_priority,
                    "created_date": created_time,
                }
            )
        logger.debug("%s %s", "data list: ", data_list)
        return Response(
            {"result": 1, "data": data_list, "msg": "Alarms details on site page"}
        )


class SiteApiBasedOnSiteType(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data is: ", data)
        customer_id = data.get("customer_id")
        site_id = data.get("site_id", "")
        site = Site.objects.get(id=site_id)
        site_type = site.site_type
        logger.debug("%s %s", "site type: ", site_type)
        data_list = []
        if site_type == 1:
            logger.debug("%s", "current site is metering. so send all sites of saving")
            sites = Site.objects.filter(customer=customer_id, site_type=2)
            for i in sites:
                data_list.append(
                    {"id": i.id, "site_name": i.site_name, "site_type": i.site_type}
                )
            logger.debug("%s %s", "all sites are: ", sites)
        elif site_type == 2:
            logger.debug("%s", "current site is saving. so send all sites of metering")
            sites = Site.objects.filter(customer=customer_id, site_type=1)
            logger.debug("%s %s", "all sites are: ", sites)
            for i in sites:
                data_list.append(
                    {"id": i.id, "site_name": i.site_name, "site_type": i.site_type}
                )
        return Response({"result": 1, "data": data_list})
