"""Load data graphs, power factor, min/max and Excel exports."""

import re
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    DailyLoadData,
    HourlyLoadData,
    MainsDgLoadData,
    MonthlyLoadSharePercentage,
    MonthlyMinMaxLoadData,
    PowerFactorData,
    RawLoadData,
    Site,
)
from wareApp.utility import logger


class LoadGrapghAPI(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            current_date = datetime.now()
            raw_data = RawLoadData.objects.filter(
                site=site_id,
                created__date=current_date.date(),
                created__hour=current_date.hour,
            )
            res = []
            for i in raw_data:
                load_data = i.load_data / 1000
                res.append(
                    {
                        "x": int(i.epoch_time),
                        "y": round(load_data, 3),
                        "aisle_name": i.aisle_group.aisleGroupName,
                        "color": i.aisle_group.load_graph_color,
                    }
                )
                # res.append({"x":x,"y":rand,"color":i.aisle_group.color})
            return Response({"status": 200, "data": sorted(res, key=lambda d: d["x"])})
        except Exception as err:
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGrapghAPITestingPurpose(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            current_date = datetime.now().replace(day=11, hour=16)
            raw_data = RawLoadData.objects.filter(
                site=site_id,
                created__date=current_date.date(),
                created__hour=current_date.hour,
            )
            res = []
            for i in raw_data:
                load_data = i.load_data / 1000
                res.append(
                    {
                        "x": int(i.epoch_time),
                        "y": round(load_data, 3),
                        "color": i.aisle_group.load_graph_color,
                    }
                )
                # res.append({"x":x,"y":rand,"color":i.aisle_group.color})
                # sorted(res, key=lambda d: d['x'])
            return Response({"status": 200, "data": sorted(res, key=lambda d: d["x"])})
        except Exception as err:
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForEverySecond(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            epoch_time = data.get("epoch_time")
            raw_data = RawLoadData.objects.using("default").filter(
                site=site_id, epoch_time__gt=epoch_time
            )
            res = []
            for i in raw_data:
                load_data = i.load_data / 1000
                res.append(
                    {
                        "x": int(i.epoch_time),
                        "y": round(load_data, 3),
                        "color": i.aisle_group.load_graph_color,
                    }
                )
                # resp.append({"x":x,"y":rand,"color":color})
            return Response({"status": 200, "data": res})
        except Exception as err:
            logger.debug("%s %s", "Error: ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForHourlyData(APIView):
    def post(self, request):
        data = request.data
        try:

            site_id = data.get("site_id")
            selected_date = data.get("date")
            selected_date = datetime.strptime(selected_date, "%Y/%m/%d")
            hourly_data = (
                HourlyLoadData.objects.using("default")
                .filter(site=site_id, created__date=selected_date.date())
                .order_by("created")
            )
            res = []
            if hourly_data.exists():
                for i in hourly_data:
                    load_data = i.load_data / 1000
                    res.append(
                        {
                            "x": int(i.epoch_time),
                            "y": round(load_data, 3),
                            "color": i.aisle_group.load_graph_color,
                            "aisle_name": i.aisle_group.aisleGroupName,
                        }
                    )
            return Response({"status": 200, "data": res})
        except Exception as err:
            logger.debug("%s %s", "Error : ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForDailyData(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            selected_date = data.get("date")
            till_date = datetime.strptime(selected_date, "%Y/%m/%d")
            from_date = till_date - timedelta(days=31)
            hourly_data = (
                DailyLoadData.objects.using("default")
                .filter(
                    site=site_id,
                    created__date__gte=from_date.date(),
                    created__date__lte=till_date.date(),
                )
                .order_by("created")
            )
            res = []
            if hourly_data.exists():
                for i in hourly_data:
                    load_data = i.load_data / 1000
                    res.append(
                        {
                            "x": int(i.epoch_time),
                            "y": round(load_data, 3),
                            "color": i.aisle_group.load_graph_color,
                            "aisle_name": i.aisle_group.aisleGroupName,
                        }
                    )
            return Response({"status": 200, "data": res})
        except Exception as err:
            logger.debug("%s %s", "Error : ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadDataExcelDownload(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            date = data.get("date")
            selected_date = datetime.strptime(date, "%Y/%m/%d")
            graph_type = data.get("graph_type")
            date_array = []
            data_array = []
            power_source = []
            if graph_type == "0":
                # download hourly data
                final_data = HourlyLoadData.objects.filter(
                    site=site_id, created__date=selected_date.date()
                ).order_by("created")
            elif graph_type == "1" or graph_type == "2":
                # download daily data
                till_date = datetime.strptime(date, "%Y/%m/%d")
                from_date = till_date - timedelta(days=31)
                final_data = DailyLoadData.objects.filter(
                    site=site_id,
                    created__date__gte=from_date.date(),
                    created__date__lte=till_date.date(),
                ).order_by("created")
            elif graph_type == "3":
                # download daily data
                till_date = datetime.strptime(date, "%Y/%m/%d")
                from_date = till_date - timedelta(days=31)
                final_data = MainsDgLoadData.objects.filter(
                    site=site_id, created__date=till_date.date()
                )
            elif graph_type == "4":
                date = datetime.now()
                final_data = RawLoadData.objects.filter(
                    site=site_id, created__date=date.date(), created__hour=date.hour
                ).order_by("created")
            else:
                # download monthly data
                final_data = []
            if final_data:
                for i in final_data:
                    load_data = i.load_data / 1000
                    if load_data > 0:
                        date_array.append(i.created.strftime("%d %b, %Y %H:%M:%S"))
                        data_array.append(round(load_data, 3))
                        if graph_type == "3":
                            power_source.append(i.aisle_group.aisleGroupName)
                if graph_type == "3":
                    df = pd.DataFrame(
                        {
                            "Date": date_array,
                            "Load Data(KW)": data_array,
                            "Power_Source": power_source,
                        }
                    )
                else:
                    df = pd.DataFrame({"Date": date_array, "Load Data(KW)": data_array})
                file_name = "load_data_{}".format(date)
                response = HttpResponse(
                    content_type="text/csv",
                )
                response["filename"] = file_name
                response["Content-Disposition"] = "attachment; filename={}".format(
                    file_name
                )
                df.to_csv(response, index=False)
                return response
            else:
                return Response(
                    {
                        "status": 500,
                        "data": [],
                        "msg": "No data for selected graph and date",
                    }
                )
        except Exception as err:
            logger.debug("%s", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class FetchFluctuatedPowerFactor(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            pf = PowerFactorData.objects.filter(site=site_id)
            res = []
            if pf.exists():
                for i in pf:
                    r_phase = (
                        str(round(i.r_phase_pf, 3)) + " PF Not Ok"
                        if i.r_phase_pf > 0
                        else "PF Normal"
                    )
                    y_phase = (
                        str(round(i.y_phase_pf, 3)) + " PF Not Ok"
                        if i.y_phase_pf > 0
                        else "PF Normal"
                    )
                    b_phase = (
                        str(round(i.b_phase_pf, 3)) + " PF Not Ok"
                        if i.b_phase_pf > 0
                        else "PF Normal"
                    )
                    res.append(
                        {
                            "created": i.created.strftime("%d %b, %Y %H:%M:%S"),
                            "power_source": i.supply_source,
                            "r_phase": r_phase,
                            "y_phase": y_phase,
                            "b_phase": b_phase,
                        }
                    )
            return Response({"status": 200, "data": res})
        except Exception as err:
            logger.debug("%s", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class FetchMinMaxMonthlyLoadData(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("id")
            monthly_load_data = MonthlyMinMaxLoadData.objects.filter(
                site=site_id
            ).order_by("created")
            res = []
            min = 100000
            max = 0
            min_date = ""
            max_date = ""
            if monthly_load_data.exists():
                for i in monthly_load_data:
                    if min > i.min_load:
                        min = i.min_load / 1000 if i.min_load else 0.0
                        min_date = i.created.strftime("%d %b, %Y %H:%M:%S")
                    if max < i.max_load:
                        max = i.max_load / 1000 if i.max_load else 0.0
                        max_date = i.created.strftime("%b %m %Y %H:%M:%S")
                    min_load = i.min_load / 1000
                    max_load = i.max_load / 1000
                    res.append(
                        {
                            "created": i.created.strftime("%b %m %Y %H:%M:%S"),
                            "power_source": i.supply_source,
                            "min_load": round(min_load, 3),
                            "min_load_created": i.min_load_created.strftime(
                                "%d %b, %Y %H:%M:%S"
                            ),
                            "max_load": round(max_load, 3),
                            "max_load_created": i.max_load_created.strftime(
                                "%d %b, %Y %H:%M:%S"
                            ),
                            "month": i.max_load_created.strftime("%b, %Y"),
                        }
                    )
                return Response(
                    {
                        "status": 200,
                        "data": res,
                        "min_value": min,
                        "min_date": min_date,
                        "max_value": max,
                        "max_date": max_date,
                    }
                )
            return Response({"status": 500, "data": [], "msg": "No records exists"})
        except Exception as err:
            logger.debug("%s", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class DownloadMinMaxMonthlyLoadData(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            monthly_load_data = MonthlyMinMaxLoadData.objects.filter(
                site=site_id
            ).order_by("created")
            power_source_array = []
            min_load_array = []
            min_load_date_array = []
            max_load_array = []
            max_load_date_array = []
            month_year = []
            if monthly_load_data.exists():
                for i in monthly_load_data:
                    min_load = i.min_load / 1000
                    max_load = i.max_load / 1000
                    power_source_array.append(i.supply_source)
                    min_load_array.append(round(min_load, 3))
                    min_load_date_array.append(
                        i.min_load_created.strftime("%d %b, %Y %H:%M:%S")
                    )
                    max_load_array.append(round(max_load, 3))
                    max_load_date_array.append(
                        i.max_load_created.strftime("%d %b, %Y %H:%M:%S")
                    )
                    month_year.append(i.max_load_created.strftime("%b, %Y"))
                df = pd.DataFrame(
                    {
                        "PowerSource": power_source_array,
                        "Min_Load_Value": min_load_array,
                        "Min_Load_Date": min_load_date_array,
                        "Max_Load_Value": max_load_array,
                        "Max_Load Date": max_load_date_array,
                        "month": month_year,
                    }
                )
                file_name = "monthly_min_max_data"
                response = HttpResponse(
                    content_type="text/csv",
                )
                response["filename"] = file_name
                response["Content-Disposition"] = "attachment; filename={}".format(
                    file_name
                )
                df.to_csv(response)
                return response
            return Response({"status": 500, "data": [], "msg": "No records exists"})
        except Exception as err:
            logger.debug("%s", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class DownloadFluctuatedPowerFactor(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            pf = PowerFactorData.objects.filter(site=site_id)
            date_array = []
            r_phase_array = []
            y_phase_array = []
            b_phase_array = []
            power_source_array = []
            if pf.exists():
                for i in pf:
                    r_phase = (
                        str(round(i.r_phase_pf, 3)) + " PF Not Ok"
                        if i.r_phase_pf > 0
                        else "PF Normal"
                    )
                    y_phase = (
                        str(round(i.y_phase_pf, 3)) + " PF Not Ok"
                        if i.y_phase_pf > 0
                        else "PF Normal"
                    )
                    b_phase = (
                        str(round(i.b_phase_pf, 3)) + " PF Not Ok"
                        if i.b_phase_pf > 0
                        else "PF Normal"
                    )
                    date_array.append(i.created.strftime("%d %b, %Y %H:%M:%S"))
                    r_phase_array.append(r_phase)
                    y_phase_array.append(y_phase)
                    b_phase_array.append(b_phase)
                    power_source_array.append(i.supply_source)
                df = pd.DataFrame(
                    {
                        "Date": date_array,
                        "PowerSource": power_source_array,
                        "R-Phase": r_phase_array,
                        "Y-Phase": y_phase_array,
                        "B-Phase": b_phase_array,
                    }
                )
                file_name = "pf_data"
                response = HttpResponse(
                    content_type="text/csv",
                )
                response["filename"] = file_name
                response["Content-Disposition"] = "attachment; filename={}".format(
                    file_name
                )
                df.to_csv(response)
                return response
            return Response({"status": 500, "data": []})
        except Exception as err:
            logger.debug("%s", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForMainsDgDailyData(APIView):
    @staticmethod
    def _series_color(series_name):
        normalized_name = str(series_name or "").strip().lower()
        match = re.search(r"(\d+)$", normalized_name)
        series_index = int(match.group(1)) if match else 1

        if "dg" in normalized_name:
            palette = {
                1: "#FFD580",
                2: "#FFB347",
                3: "#FF9F5A",
            }
            return palette.get(series_index, "#FFD580")

        palette = {
            1: "#90EE90",
            2: "#B6F2B6",
        }
        return palette.get(series_index, "#90EE90")

    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            selected_date = data.get("date")
            till_date = datetime.strptime(selected_date, "%Y/%m/%d")
            from_date = till_date - timedelta(days=31)
            all_aisles = AisleGroup.objects.filter(site=site_id).order_by("id")
            final_data = []
            for aisle in all_aisles:
                series_color = self._series_color(aisle.aisleGroupName)
                hourly_data = (
                    MainsDgLoadData.objects.using("default")
                    .filter(
                        site=site_id,
                        aisle_group=aisle.id,
                        created__date=till_date.date(),
                    )
                    .order_by("created")
                )
                res = {"name": aisle.aisleGroupName, "color": series_color}
                if hourly_data.exists():
                    res["data"] = []
                    for i in hourly_data:
                        load_data = i.load_data / 1000
                        res["data"].append(
                            {
                                "x": int(i.epoch_time),
                                "y": round(load_data, 3),
                                "color": series_color,
                            }
                        )
                final_data.append(res)
            return Response({"status": 200, "data": final_data})
        except Exception as err:
            logger.debug("%s %s", "Error : ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadDataApi(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        try:
            selected_date = datetime.strptime(data.get("date"), "%Y/%m/%d")
            hourlyLoadData = (
                HourlyLoadData.objects.filter(
                    aisle_group_id=data.get("aisle_id"),
                    created__date=selected_date.date(),
                )
                .order_by("created")
                .values("epoch_time", "load_data", "aisle_group__load_graph_color")
            )

            if hourlyLoadData.exists():
                res = [
                    {
                        "x": int(i["epoch_time"]),
                        "y": round(i["load_data"] / 1000, 3),
                        "color": i["aisle_group__load_graph_color"],
                    }
                    for i in hourlyLoadData
                ]
                return Response({"status": 200, "data": res})
            else:
                res = [{"x": 0, "y": int(datetime.now().timestamp())}]
                return Response({"status": 404, "data": res})
        except Exception as err:
            return Response(
                {"status": 500, "message": "Internal Server Error", "error": str(err)}
            )


class LoadDataApiMultipleSource(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        date_str = data.get("date")
        site_id = data.get("site_id")

        if not date_str or not site_id:
            return Response({"error": "Missing 'date' or 'site_id'"}, status=400)

        try:
            selected_date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response(
                {"error": "Invalid date format. Expected YYYY/MM/DD"}, status=400
            )

        try:
            aisle_groups = AisleGroup.objects.filter(site_id=site_id).values(
                "id", "aisleGroupName"
            )
            aisle_group_ids = [g["id"] for g in aisle_groups]

            hourly_data = (
                HourlyLoadData.objects.filter(
                    aisle_group_id__in=aisle_group_ids,
                    created__date=selected_date.date(),
                )
                .order_by("created")
                .values(
                    "epoch_time",
                    "load_data",
                    "aisle_group__load_graph_color",
                    "aisle_group__aisleGroupName",
                )
            )

            grouped_data = defaultdict(list)
            for row in hourly_data:
                name = row["aisle_group__aisleGroupName"]
                grouped_data[name].append(
                    {
                        "x": int(row["epoch_time"]),
                        "y": round(row["load_data"] / 1000, 3),
                        "color": row["aisle_group__load_graph_color"],
                    }
                )

            response_data = [
                {group["aisleGroupName"]: grouped_data.get(group["aisleGroupName"], [])}
                for group in aisle_groups
            ]

            return Response({"data": response_data, "status": 200})
        except Exception as err:
            return Response(
                {"error": str(err), "message": "Internal Server Error"}, status=500
            )


class LoadDataApiMultipleSourceV2(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        date_str = data.get("date")
        site_id = data.get("site_id")

        if not date_str or not site_id:
            return Response({"error": "Missing 'date' or 'site_id'"}, status=400)

        try:
            selected_date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response(
                {"error": "Invalid date format. Expected YYYY/MM/DD"}, status=400
            )

        try:
            aisle_groups = AisleGroup.objects.filter(site_id=site_id).values(
                "id", "aisleGroupName"
            )
            aisle_group_ids = [g["id"] for g in aisle_groups]

            hourly_data = (
                HourlyLoadData.objects.filter(
                    aisle_group_id__in=aisle_group_ids,
                    created__date=selected_date.date(),
                )
                .order_by("created")
                .values(
                    "epoch_time",
                    "load_data",
                    "aisle_group__load_graph_color",
                    "aisle_group__aisleGroupName",
                )
            )

            grouped_data = defaultdict(list)
            for row in hourly_data:
                name = row["aisle_group__aisleGroupName"]
                grouped_data[name].append(
                    {
                        "x": int(row["epoch_time"]),
                        "y": round(row["load_data"] / 1000, 3),
                        "color": row["aisle_group__load_graph_color"],
                    }
                )

            GAP_THRESHOLD = 300000  # 5 min

            filled_grouped_data = {}
            for name, points in grouped_data.items():
                filled = []
                for i, point in enumerate(points):
                    filled.append(point)

                    if i + 1 < len(points):
                        next_point = points[i + 1]
                        gap = next_point["x"] - point["x"]

                        if gap > GAP_THRESHOLD:
                            # Instead of thousands of zeros, insert a gap marker
                            filled.append(
                                {
                                    "from": point["x"] + 1,
                                    "to": next_point["x"] - 1,
                                    "y": 0,
                                    "color": point["color"],
                                }
                            )

                filled_grouped_data[name] = filled

            response_data = [
                {
                    group["aisleGroupName"]: filled_grouped_data.get(
                        group["aisleGroupName"], []
                    )
                }
                for group in aisle_groups
            ]

            return Response({"data": response_data, "status": 200})

        except Exception as err:
            return Response(
                {"error": str(err), "message": "Internal Server Error"}, status=500
            )


class LiveDataApi(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        site_id = data.get("site_id", 0)
        epoch_time = data.get("epoch_time", 0)
        try:
            load_data = RawLoadData.objects.filter(
                aisle_group__site_id=site_id, epoch_time__gt=epoch_time
            ).prefetch_related("aisle_group")
            grouped_data = defaultdict(list)
            for obj in load_data:
                grouped_data[obj.aisle_group.aisleGroupName].append(
                    {"load": obj.load_data / 1000, "epoch": obj.epoch_time}
                )
            response = {"data": dict(grouped_data)}
            return Response(response)
        except Exception as err:
            return Response({"message": str(err)})


class LoadDataExcelDownloadMonthlyRange(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            from_date = data.get("from_date")
            end_date = data.get("end_date")
            graph_type = data.get("graph_type")

            # Parse dates
            start_date = datetime.strptime(from_date, "%Y/%m/%d")
            till_date = datetime.strptime(end_date, "%Y/%m/%d")

            # Get site name for filename
            try:
                site = Site.objects.get(id=site_id)
                site_name = site.site_name.replace(" ", "").replace(
                    "/", ""
                )  # Clean site name for filename
            except Site.DoesNotExist:
                site_name = f"Site_{site_id}"

            date_array = []
            data_array = []
            power_source = []

            if graph_type == "0":
                # Hourly data for date range
                final_data = HourlyLoadData.objects.filter(
                    site=site_id,
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date(),
                ).order_by("created")
            elif graph_type == "1":
                # Daily data for date range
                final_data = DailyLoadData.objects.filter(
                    site=site_id,
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date(),
                ).order_by("created")
            elif graph_type == "2":
                # Custom date range daily data - uses exact date range provided
                final_data = DailyLoadData.objects.filter(
                    site=site_id,
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date(),
                ).order_by("created")
            elif graph_type == "3":
                # MainsDg data for date range
                final_data = MainsDgLoadData.objects.filter(
                    site=site_id,
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date(),
                ).order_by("created")
            elif graph_type == "4":
                # Raw data for date range
                final_data = RawLoadData.objects.filter(
                    site=site_id,
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date(),
                ).order_by("created")
            else:
                # Monthly data for date range
                final_data = MonthlyLoadSharePercentage.objects.filter(
                    site=site_id,
                    created_on__date__gte=start_date.date(),
                    created_on__date__lte=till_date.date(),
                ).order_by("created_on")

            if final_data:
                for i in final_data:
                    if hasattr(i, "load_data"):
                        load_data = i.load_data / 1000
                    elif hasattr(i, "total_load"):
                        load_data = i.total_load / 1000
                    else:
                        load_data = 0

                    if load_data > 0:
                        if hasattr(i, "created"):
                            date_array.append(i.created.strftime("%d %b, %Y %H:%M:%S"))
                        elif hasattr(i, "created_on"):
                            date_array.append(
                                i.created_on.strftime("%d %b, %Y %H:%M:%S")
                            )

                        data_array.append(round(load_data, 3))

                        if (graph_type == "3" or graph_type == "4") and hasattr(
                            i, "aisle_group"
                        ):
                            power_source.append(i.aisle_group.aisleGroupName)

                if graph_type == "3" or graph_type == "4":
                    df = pd.DataFrame(
                        {
                            "Date": date_array,
                            "Load Data(KW)": data_array,
                            "Power_Source": power_source,
                        }
                    )
                else:
                    df = pd.DataFrame({"Date": date_array, "Load Data(KW)": data_array})

                file_name = f"{site_name}load_data_monthly_range{from_date.replace('/', '')}_to{end_date.replace('/', '_')}.csv"
                response = HttpResponse(content_type="text/csv")
                response["filename"] = file_name
                response["Content-Disposition"] = f"attachment; filename={file_name}"
                df.to_csv(response, index=False)
                return response
            else:
                return Response(
                    {
                        "status": 500,
                        "data": [],
                        "msg": "No data found for the selected date range and graph type",
                    }
                )

        except Exception as err:
            logger.debug("%s", err)
            return Response({"status": 500, "data": [], "msg": str(err)})
