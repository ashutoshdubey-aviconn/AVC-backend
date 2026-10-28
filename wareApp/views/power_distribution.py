"""Power-source distribution charts (mains / DG / solar)."""

from datetime import datetime, timedelta

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    DailySiteReading,
    HourlySiteReading,
    Site,
    SupplyLoadTimeShare,
)
from wareApp.utility import entryExit, logger


class PowerSourceDistributionMonthlyBarChartTime(APIView):
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "request data :", data)
        site_id = data.get("site_id", "")
        from_date = data.get("from_date", "")
        till_date = data.get("till_date", "")
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        logger.debug("%s %s %s %s", "fromDate : ", fromDate, " tillDate: ", tillDate)
        currentDate = datetime.now()
        logger.debug("%s %s", "currentDate: ", currentDate)
        dateList = []
        dataList = []
        if tillDate.month == currentDate.month:
            logger.debug("%s", "###### inside current month  ######")
            for power_source in (
                SupplyLoadTimeShare.objects.distinct("power_source")
                .order_by("power_source")
                .filter(site=site_id)
            ):
                logger.debug("%s %s", "power source", power_source)
                dateList = []
                day_data_list = []
                for i in range(30):
                    date = tillDate.date() - timedelta(days=29 - i)
                    dateList.append(date)
                    logger.debug("%s %s", "date : ", date)
                    graph = SupplyLoadTimeShare.objects.filter(
                        site=site_id,
                        power_source=power_source.power_source,
                        reading_from__date=date,
                    )
                    logger.debug("%s %s", "all graph object :", graph)
                    run_time = 0.0
                    if graph.exists():
                        for j in graph:
                            run_time += j.hourly_run_time
                    day_data_list.append(run_time)
                power_source = power_source.get_power_source_display()
                dataList.append({"name": power_source, "data": day_data_list})
            dataPercentage = []
            logger.debug("%s", "calculating the percentage")
            for i in range(len(dataList)):
                x = []
                a = len(dataList[i]["data"])
                for j in range(0, a):
                    p = abs(dataList[i]["data"][j])
                    b = 0.0
                    for k in range(len(dataList)):
                        b += abs(dataList[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 1)
                    except Exception as e:
                        t = round(p, 2)
                    x.append(t)
                dataPercentage.append({"name": dataList[i]["name"], "data": x})

            logger.debug("%s", "percentage calculate")
            return Response({"Dates": dateList, "Data": dataList})
        else:
            logger.debug("%s", "###### inside different month #####")
            for power_source in (
                SupplyLoadTimeShare.objects.distinct("power_source")
                .order_by("power_source")
                .filter(site=site_id)
            ):
                dateList = []
                total_days = (tillDate.day - fromDate.day) + 1
                logger.debug("%s %s", "total days are : ", total_days)
                a = []
                for i in range(0, total_days):
                    date = fromDate.date() + timedelta(days=i)
                    logger.debug("%s %s", "date: ", date)
                    dateList.append(date)
                    graph = SupplyLoadTimeShare.objects.filter(
                        site=site_id,
                        power_source=power_source.power_source,
                        reading_from__date=date,
                    )
                    logger.debug("%s %s", "all graph object: ", graph)
                    run_time = 0.0
                    if graph.exists():
                        for j in graph:
                            run_time += j.hourly_run_time
                    a.append(run_time)
                power_source = power_source.get_power_source_display()
                dataList.append({"name": power_source, "data": a})
            dataPercentage = []
            logger.debug("%s", "calculating the percentage")
            for i in range(len(dataList)):
                x = []
                a = len(dataList[i]["data"])
                for j in range(0, a):
                    p = abs(dataList[i]["data"][j])
                    b = 0.0
                    for k in range(len(dataList)):
                        b += abs(dataList[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 2)
                    except Exception as e:
                        t = p
                    x.append(t)

                dataPercentage.append({"name": dataList[i]["name"], "data": x})
            logger.debug("%s", "percentage calculate")
            return Response({"Dates": dateList, "Data": dataList})


class PowerDistributionHourlyBarChartTime(APIView):
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        date = data.get("date", "")
        date = datetime.strptime(date, "%Y/%m/%d")
        hourList = []
        dataList = []
        for power_source in (
            SupplyLoadTimeShare.objects.distinct("power_source")
            .order_by("power_source")
            .filter(site=site_id)
        ):
            hour_data_list = []
            hourList = []
            for i in range(24):
                hour = i
                if hour <= 9:
                    hr = "0" + str(hour) + ":00"
                else:
                    hr = str(hour) + ":00"
                logger.debug("%s %s", "hour : ", hr)
                hourList.append(hr)
                graph = SupplyLoadTimeShare.objects.filter(
                    site=site_id,
                    power_source=power_source.power_source,
                    reading_from__date=date,
                    reading_from__hour=hour,
                )
                logger.debug("%s %s", "all graph object :", graph)
                run_time = 0.0
                if graph.exists():
                    for j in graph:
                        run_time += j.hourly_run_time
                hour_data_list.append(run_time)
            power_source = power_source.get_power_source_display()
            dataList.append({"name": power_source, "data": hour_data_list})

        dataPercentage = []
        logger.debug("%s", "calculating the percentage")
        for i in range(len(dataList)):
            x = []
            a = len(dataList[i]["data"])
            for j in range(0, a):
                p = abs(dataList[i]["data"][j])
                b = 0.0
                for k in range(len(dataList)):
                    b += abs(dataList[k]["data"][j])
                try:
                    t = round(p * 100 / b, 2)
                except Exception as e:
                    t = p
                x.append(t)
            dataPercentage.append({"name": dataList[i]["name"], "data": x})
        logger.debug("%s", "percentage calculate")
        return Response({"Hours": hourList, "Data": dataPercentage})


class PowerSourceDistributionMonthlyBarChart(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        till_date = data.get("till_date", "")
        logger.debug("%s %s", "till_date", till_date)
        from_date = data.get("from_date", "")
        logger.debug("%s %s", "from date: ", from_date)
        site_id = data.get("site_id", " ")
        logger.debug("%s %s", "This is the site id: ", site_id)
        site = Site.objects.get(id=int(site_id))
        logger.debug("%s %s", "site: ", site)
        try:
            from_date = datetime.strptime(from_date, "%Y/%m/%d")
            till_date = datetime.strptime(till_date, "%Y/%m/%d")
            data = []
            dates = []
            logger.debug("%s", "distinct legs")
            for leg in DailySiteReading.objects.distinct("leg_id").filter(
                associated_Site=int(site_id)
            ):
                daily_consumption = []
                dates = []
                logger.debug("%s", "limits")
                dateLowerLimitCheck = from_date.date()
                dateUpperLimitCheck = till_date.date()
                logger.debug("%s %s", "dateUpperLimitCheck", dateUpperLimitCheck)
                given_date_graph_data = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id=leg,
                    reading_for__gte=dateLowerLimitCheck,
                    reading_for__lte=dateUpperLimitCheck,
                )
                date = from_date.date()
                logger.debug("%s %s", "date", date)
                logger.debug("%s", "LOOP!!")
                for i in range(31):
                    if date <= till_date.date():
                        dates.append(date)
                        logger.debug("%s %s", "here is range date", date)
                        if given_date_graph_data.filter(reading_for=date).exists():
                            one_day_consumption = round(
                                given_date_graph_data.filter(reading_for=date)[
                                    0
                                ].unit_consumption,
                                2,
                            )
                        else:
                            one_day_consumption = 0
                        daily_consumption.append(one_day_consumption)
                    else:
                        break

                    if AisleGroup.objects.filter(attached_leg_id=leg).exists():
                        aisle_group = AisleGroup.objects.get(
                            attached_leg_id=leg
                        ).aisleGroupName
                    else:
                        aisle_group = str(leg)
                    date = date + timedelta(days=1)
                singleData = {"name": aisle_group, "data": daily_consumption}
                data.append(singleData)
            dataPercentage = []
            logger.debug("%s", "calculating the percentage")
            for i in range(len(data)):
                x = []
                a = len(data[i]["data"])
                for j in range(0, a):
                    p = abs(data[i]["data"][j])
                    b = 0.0
                    for k in range(len(data)):
                        b += abs(data[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 1)
                    except Exception as e:
                        t = round(p, 2)
                    x.append(t)
                dataPercentage.append({"name": data[i]["name"], "data": x})
            logger.debug("%s", "percentage calculate")
            return Response({"Dates": dates, "Data": dataPercentage})
        except Exception as e:
            logger.debug("%s %s", "exception is ", e)
            return Response({"error": "errorrrrrrrrrrrrrrrrr"})


class PowerDistributionHourlyBarChart(APIView):
    @entryExit
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
            for leg in HourlySiteReading.objects.distinct("leg_id").filter(
                associated_Site=site
            ):
                logger.debug("%s %s", "leg id is:", leg)
                hourly_consumption = []
                hours = []
                for i in range(24):
                    hr = i
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
                logger.debug("%s %s", "singleData:", singleData)
                data.append(singleData)
            dataPercentage = []
            logger.debug("%s", "calculating the percentage")
            for i in range(len(data)):
                x = []
                a = len(data[i]["data"])
                logger.debug("%s %s", "here is a value :", a)
                for j in range(0, a):
                    p = abs(data[i]["data"][j])
                    b = 0.0
                    for k in range(len(data)):
                        b += abs(data[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 2)
                    except Exception as e:
                        t = p
                    x.append(t)

                dataPercentage.append({"name": data[i]["name"], "data": x})
            logger.debug("%s", "percentage calculate")
            return Response({"Hours": hours, "Data": dataPercentage})

        except Exception as e:
            logger.debug("%s %s", "exception is ", e)
            return Response({"error": "errorrrrrrrrrrrrrrrrr"})


class PowerDistributionPieChartV2(APIView):
    permission_classes = [AllowAny]

    @staticmethod
    def _parse_month_year(data):
        current_date = datetime.now()
        month = data.get("month") or data.get("selected_month")
        year = data.get("year") or data.get("selected_year")

        try:
            month = int(month) if month not in (None, "") else current_date.month
            year = int(year) if year not in (None, "") else current_date.year
        except (TypeError, ValueError):
            return None, None, "month and year must be valid integers"

        if month < 1 or month > 12:
            return None, None, "month must be between 1 and 12"
        if year < 1:
            return None, None, "year must be a valid year"

        return month, year, None

    def post(self, request):
        try:
            site_id = request.data.get("siteId") or request.data.get("site_id")
            if not site_id:
                return Response(
                    {"error": "SiteID is required"}, status=status.HTTP_400_BAD_REQUEST
                )

            try:
                site_id = int(site_id)
            except (TypeError, ValueError):
                return Response(
                    {"error": "SiteID must be a valid integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            month, year, parse_error = self._parse_month_year(request.data)
            if parse_error:
                return Response(
                    {"error": parse_error}, status=status.HTTP_400_BAD_REQUEST
                )

            base_readings = DailySiteReading.objects.filter(
                associated_Site_id=site_id,
                reading_for__isnull=False,
            )

            available_months = [
                {
                    "month": item["month"].month,
                    "year": item["month"].year,
                    "label": item["month"].strftime("%b-%Y"),
                }
                for item in base_readings.annotate(month=TruncMonth("reading_for"))
                .values("month")
                .distinct()
                .order_by("-month")
            ]

            readings = list(
                base_readings.filter(reading_for__year=year, reading_for__month=month)
                .values("leg_id")
                .annotate(total_units=Sum("unit_consumption"))
                .order_by("leg_id")
            )

            leg_ids = [r["leg_id"] for r in readings]

            aisle_groups = {
                ag.attached_leg_id: ag.aisleGroupName
                for ag in AisleGroup.objects.filter(
                    site_id=site_id, attached_leg_id__in=leg_ids
                ).only("attached_leg_id", "aisleGroupName")
            }

            source_totals = {}
            for r in readings:
                leg_id = r["leg_id"]
                source_name = aisle_groups.get(leg_id, str(leg_id))
                source_totals[source_name] = source_totals.get(source_name, 0) + (
                    r["total_units"] or 0
                )

            total_sum = sum(source_totals.values())
            finalData = []

            for name, total in source_totals.items():
                percentage = total * 100 / total_sum if total_sum else 0
                finalData.append({"name": name, "data": round(percentage, 2)})

            selected_date = datetime(year=year, month=month, day=1)
            previous_month_date = selected_date - timedelta(days=1)
            previous_month_available = any(
                item["month"] == previous_month_date.month
                and item["year"] == previous_month_date.year
                for item in available_months
            )

            response_data = {
                "result": 1,
                "data": finalData,
                "current_month": selected_date.strftime("%b-%Y"),
                "selected_month": {
                    "month": month,
                    "year": year,
                    "label": selected_date.strftime("%b-%Y"),
                },
                "available_months": available_months,
                "previous_month_available": previous_month_available,
            }
            return Response(response_data)

        except Exception as e:
            return Response({"status": 500, "msg": str(e)})


class PowerSource(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        try:
            site = data.get("site_id")
            sources = AisleGroup.objects.filter(site_id=site, is_this_power_source=True)

            response = [
                {
                    "id": i.id,
                    "aisleGroupName": i.aisleGroupName,
                    "powerSource": i.power_source,
                }
                for i in sources
            ]
            return Response(
                {
                    "data": response,
                    "result": 1,
                },
                status=200,
            )
        except Exception as err:
            return Response(
                {"error": str(err), "message": "Internal Server Error"}, status=500
            )
