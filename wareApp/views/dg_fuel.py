"""DG fuel consumption, alerts, trends and exports."""

from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.db.models import Avg, Q, Sum
from django.db.models.functions import TruncMinute, TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    DailySiteReading,
    DGAlertsData,
    DGFuelAlertsData,
    DgFuelConsumptionData,
    DgUnitConsumption,
    Site,
)
from wareApp.utility import entryExit, logger

from .common import (
    _dg_fuel_queryset,
    epoch_milliseconds,
    extract_loconav_subscription_expired_errors,
    extract_roadcast_subscription_expired_errors,
    fetch_loconav_report,
    fetch_roadcast_pull_api,
)


class DgFuelConsumptionDataApi_new(APIView):
    """
    This API is used to get the DG fuel consumption data for a site on a given date. Uses the Loconav Push API for the process.
    """

    permission_classes = [AllowAny]

    @staticmethod
    def _row_value(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def _graph_epoch_ms(value, offset_minutes=0):
        epoch_ms = epoch_milliseconds(value)
        if epoch_ms is None:
            return None
        return epoch_ms + (offset_minutes * 60 * 1000)

    @staticmethod
    def _dg_graph_base_time(row):
        value = DgFuelConsumptionDataApi_new._row_value(row, "dg_end_date")
        return epoch_milliseconds(value)

    @staticmethod
    def _day_bounds(selected_date):
        day_start = datetime.combine(selected_date, datetime.min.time())
        day_end = datetime.combine(
            selected_date, datetime.max.time().replace(microsecond=0)
        )
        if timezone.is_naive(day_start):
            current_timezone = timezone.get_current_timezone()
            day_start = timezone.make_aware(day_start, current_timezone)
            day_end = timezone.make_aware(day_end, current_timezone)
        return day_start, day_end

    @staticmethod
    def _fuel_point_from_row(row):
        fuel_value = DgFuelConsumptionDataApi_new._row_value(row, "fuel_consumption")
        epoch_value = DgFuelConsumptionDataApi_new._row_value(row, "epoch_time")
        if fuel_value is None or epoch_value is None:
            return None
        epoch_ms = epoch_milliseconds(epoch_value)
        if epoch_ms is None:
            return None
        try:
            normalized_fuel = round(float(fuel_value), 2)
        except (TypeError, ValueError):
            return None
        return {"x": epoch_ms, "y": normalized_fuel}

    @staticmethod
    def _latest_known_fuel_before(site_id, selected_date):
        previous = (
            _dg_fuel_queryset(DgFuelConsumptionData.objects)
            .filter(site=site_id, created__date__lt=selected_date)
            .order_by("-created", "-id")
            .first()
        )
        if previous is None:
            return None
        fuel_value = DgFuelConsumptionDataApi_new._row_value(
            previous, "fuel_consumption"
        )
        if fuel_value is None:
            return None
        try:
            return round(float(fuel_value), 2)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _roadcast_subscription_expired(site, selected_date):
        provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
        if provider != "roadcast":
            return False

        vehicle_imei = (getattr(site, "partner_dg_fuel_id", None) or "").strip()
        if not vehicle_imei:
            return False

        try:
            payload = fetch_roadcast_pull_api()
        except Exception:
            return False

        return bool(
            extract_roadcast_subscription_expired_errors(
                payload, site=site, vehicle_imei=vehicle_imei
            )
        )

    @staticmethod
    def _loconav_subscription_expired(site, selected_date):
        provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
        if provider != "loconav":
            return False

        vehicle_number = (getattr(site, "partner_dg_fuel_id", None) or "").strip()
        if not vehicle_number:
            return False

        day_start, day_end = DgFuelConsumptionDataApi_new._day_bounds(selected_date)
        try:
            payload = fetch_loconav_report(vehicle_number, day_start, day_end)
        except Exception:
            return False

        return bool(extract_loconav_subscription_expired_errors(payload))

    @staticmethod
    def _get_provider_status(site, selected_date):
        provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
        if provider == "roadcast":
            return (
                "SUBSCRIPTION_EXPIRED"
                if DgFuelConsumptionDataApi_new._roadcast_subscription_expired(
                    site, selected_date
                )
                else "OK"
            )
        if provider == "loconav":
            return (
                "SUBSCRIPTION_EXPIRED"
                if DgFuelConsumptionDataApi_new._loconav_subscription_expired(
                    site, selected_date
                )
                else "OK"
            )
        return "OK"

    @staticmethod
    def _expired_graph_response():
        return {
            "status": 200,
            "provider_status": "SUBSCRIPTION_EXPIRED",
            "message": "DG fuel subscription expired",
            "fuel_level": {
                "name": "Fuel Level",
                "data": [],
                "type": "column",
            },
            "data": [],
            "refuel_alert": {
                "name": "Refuel",
                "data": [],
                "type": "column",
            },
            "theft_alert": {
                "name": "Fuel Drain",
                "data": [],
                "type": "column",
            },
            "dg_unit_data": {
                "name": "DG_Unit_Consumption",
                "data": [],
                "type": "column",
            },
            "dg_fuel_data": {
                "name": "DG_Fuel_Consumed",
                "data": [],
                "type": "column",
            },
            "dg_fuel_consumed": {
                "name": "DG_Fuel_Consumed",
                "data": [],
                "type": "column",
            },
            "dg_unit_per_litre_data": {
                "name": "Dg_Unit_Per_Ltr",
                "data": [],
                "type": "column",
            },
            "dg_unit_per_litre": {
                "name": "Dg_Unit_Per_Ltr",
                "data": [],
                "type": "column",
            },
            "sample": "false",
        }

    @staticmethod
    def _fuel_level_series_for_day(site, selected_date, provider_status=None):
        today = timezone.now().date()
        day_start, day_end = DgFuelConsumptionDataApi_new._day_bounds(selected_date)
        day_start_ms = epoch_milliseconds(day_start)
        day_end_ms = epoch_milliseconds(day_end)

        if provider_status is None:
            provider_status = DgFuelConsumptionDataApi_new._get_provider_status(
                site, selected_date
            )

        if provider_status == "SUBSCRIPTION_EXPIRED":
            return []

        actual_points = []

        fuel_rows = (
            _dg_fuel_queryset(DgFuelConsumptionData.objects)
            .filter(site=site.id, created__date=selected_date)
            .order_by("created")
        )
        for row in fuel_rows:
            point = DgFuelConsumptionDataApi_new._fuel_point_from_row(row)
            if point is not None:
                actual_points.append(point)

        if not actual_points:
            previous_fuel = DgFuelConsumptionDataApi_new._latest_known_fuel_before(
                site.id, selected_date
            )
            if previous_fuel is None:
                return []
            if selected_date == today:
                current_point = {
                    "x": epoch_milliseconds(timezone.now()),
                    "y": previous_fuel,
                }
                return [
                    {"x": day_start_ms, "y": previous_fuel},
                    current_point,
                ]
            return [
                {"x": day_start_ms, "y": previous_fuel},
                {"x": day_end_ms, "y": previous_fuel},
            ]

        series = []
        first_point = actual_points[0]
        last_point = actual_points[-1]

        if first_point["x"] != day_start_ms:
            series.append({"x": day_start_ms, "y": first_point["y"]})

        series.extend(actual_points)

        if selected_date != today and last_point["x"] != day_end_ms:
            series.append({"x": day_end_ms, "y": last_point["y"]})

        deduped_series = []
        seen_timestamps = set()
        for point in series:
            timestamp = point["x"]
            if timestamp in seen_timestamps:
                continue
            seen_timestamps.add(timestamp)
            deduped_series.append(point)
        return deduped_series

    @staticmethod
    def _fuel_level_series_for_range(site, from_date, end_date):
        points = []
        current_date = from_date
        while current_date <= end_date:
            points.extend(
                DgFuelConsumptionDataApi_new._fuel_level_series_for_day(
                    site, current_date
                )
            )
            current_date += timedelta(days=1)

        deduped_series = []
        seen_timestamps = set()
        for point in sorted(points, key=lambda item: item["x"]):
            timestamp = point["x"]
            if timestamp in seen_timestamps:
                continue
            seen_timestamps.add(timestamp)
            deduped_series.append(point)
        return deduped_series

    @staticmethod
    def _normalized_alert_series(site_id, start_date, end_date):
        refuel_data = []
        theft_data = []
        alerts = (
            _dg_fuel_queryset(DGFuelAlertsData.objects)
            .filter(
                site=site_id,
                created__date__gte=start_date,
                created__date__lte=end_date,
                alert_name__in=["refuel", "theft"],
            )
            .order_by("created")
        )

        for alert in alerts:
            epoch_ms = epoch_milliseconds(
                DgFuelConsumptionDataApi_new._row_value(alert, "epoch_time")
            )
            if epoch_ms is None:
                continue
            alert_name = str(
                DgFuelConsumptionDataApi_new._row_value(alert, "alert_name", "")
            ).lower()
            fuel_value = DgFuelConsumptionDataApi_new._row_value(
                alert, "fuel_consumption"
            )
            if fuel_value is None:
                continue
            try:
                normalized_fuel = round(float(fuel_value), 2)
            except (TypeError, ValueError):
                continue
            point = {"x": epoch_ms, "y": normalized_fuel}
            if alert_name == "refuel":
                refuel_data.append(point)
            elif alert_name == "theft":
                theft_data.append(point)

        return refuel_data, theft_data

    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data: ", data)
        try:
            site_id = data.get("site_id")
            date = data.get("date")
            site = Site.objects.get(id=site_id)
            selected_date = datetime.strptime(date, "%Y/%m/%d").date()
            logger.debug("%s", selected_date)
            date = date.replace("/", "-")
            logger.debug("%s", date)
            provider_status = DgFuelConsumptionDataApi_new._get_provider_status(
                site, selected_date
            )
            if provider_status == "SUBSCRIPTION_EXPIRED":
                return Response(DgFuelConsumptionDataApi_new._expired_graph_response())

            final_data = DgFuelConsumptionDataApi_new._fuel_level_series_for_day(
                site, selected_date, provider_status=provider_status
            )
            dg_data = _dg_fuel_queryset(DgUnitConsumption.objects).filter(
                site=site_id, created__date=selected_date
            )
            logger.debug(final_data)
            logger.debug(dg_data)
            logger.debug("%s %s", "dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: %s", i)
                    base_epoch_ms = DgFuelConsumptionDataApi_new._dg_graph_base_time(i)
                    if base_epoch_ms is None:
                        continue
                    if i.unit_consumption is None or i.dg_fuel_consumption is None:
                        continue
                    unit_consumption = float(i.unit_consumption)
                    dg_fuel_consumption = float(i.dg_fuel_consumption)
                    if unit_consumption < 1:
                        continue
                    dg_unit_data.append(
                        {"x": base_epoch_ms, "y": round(unit_consumption, 2)}
                    )
                    dg_fuel_data.append(
                        {
                            "x": DgFuelConsumptionDataApi_new._graph_epoch_ms(
                                base_epoch_ms, 1
                            ),
                            "y": round(dg_fuel_consumption, 2),
                        }
                    )
                    if dg_fuel_consumption > 0:
                        dg_unit_per_litre.append(
                            {
                                "x": DgFuelConsumptionDataApi_new._graph_epoch_ms(
                                    base_epoch_ms, 3
                                ),
                                "y": round(unit_consumption / dg_fuel_consumption, 2),
                            }
                        )
            else:
                logger.debug("%s", "inside else")
                dg_unit_data = []
                dg_fuel_data = []
                dg_unit_per_litre = []
            refuel_data, theft_data = (
                DgFuelConsumptionDataApi_new._normalized_alert_series(
                    site_id,
                    selected_date,
                    selected_date,
                )
            )

            refuel_final_data = {
                "name": "Refuel",
                "data": refuel_data,
                "type": "column",
            }
            theft_final_data = {
                "name": "Fuel Drain",
                "data": theft_data,
                "type": "column",
            }
            dg_unit_final_data = {
                "name": "DG_Unit_Consumption",
                "data": dg_unit_data,
                "type": "column",
            }
            dg_fuel_final_data = {
                "data": dg_fuel_data,
                "type": "column",
            }
            dg_unit_per_litre_data = {
                "name": "Dg_Unit_Per_Ltr",
                "data": dg_unit_per_litre,
                "type": "column",
            }
            return Response(
                {
                    "status": 200,
                    "provider_status": provider_status,
                    "fuel_level": {
                        "name": "Fuel Level",
                        "data": final_data,
                        "type": "column",
                    },
                    "data": final_data,
                    "refuel_alert": refuel_final_data,
                    "theft_alert": theft_final_data,
                    "dg_unit_data": dg_unit_final_data,
                    "dg_fuel_data": dg_fuel_final_data,
                    "dg_fuel_consumed": dg_fuel_final_data,
                    "dg_unit_per_litre_data": dg_unit_per_litre_data,
                    "dg_unit_per_litre": dg_unit_per_litre_data,
                    "sample": "false",
                }
            )
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})


class FetchDGAlertData(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            DGAlertsData.objects.create(alert_data=data)
            return Response({"status": 200, "msg": "alert received"})
        except Exception as err:
            logger.debug("%s", err)
            return Response(
                {"status": 500, "msg": "error while receiving alerts, {}".format(err)}
            )


class DgFuelConsumptionDataApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            date = data.get("date")
            selected_date = datetime.strptime(date, "%Y/%m/%d").date()
            site = Site.objects.get(id=site_id)
            final_data = DgFuelConsumptionDataApi_new._fuel_level_series_for_day(
                site, selected_date
            )
            dg_data = _dg_fuel_queryset(DgUnitConsumption.objects).filter(
                site=site_id, created__date=selected_date
            )
            logger.debug(final_data)
            logger.debug(dg_data)
            logger.debug("%s %s", "dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: %s", i)
                    unit_consumption = getattr(i, "unit_consumption", None)
                    dg_fuel_consumption = getattr(i, "dg_fuel_consumption", None)
                    epoch_ms = epoch_milliseconds(getattr(i, "epoch_time", None))
                    if (
                        unit_consumption is None
                        or dg_fuel_consumption is None
                        or epoch_ms is None
                        or float(unit_consumption) < 1
                    ):
                        continue
                    dg_unit_data.append(
                        {"x": epoch_ms, "y": round(unit_consumption, 2)}
                    )
                    if dg_fuel_consumption is not None:
                        dg_fuel_data.append(
                            {"x": epoch_ms, "y": round(dg_fuel_consumption, 2)}
                        )
                    if dg_fuel_consumption and dg_fuel_consumption > 0:
                        dg_unit_per_litre.append(
                            {
                                "x": epoch_ms,
                                "y": round(unit_consumption / dg_fuel_consumption, 2),
                            }
                        )
            refuel_data = []
            theft_data = []
            fuel_alerts = (
                _dg_fuel_queryset(DGFuelAlertsData.objects)
                .filter(site=site_id, created__date=selected_date)
                .order_by("created")
            )
            if fuel_alerts.exists():
                for i in fuel_alerts:
                    if i.alert_name == "refuel":
                        refuel_data.append(
                            {
                                "x": epoch_milliseconds(i.epoch_time),
                                "y": round(i.fuel_consumption, 2),
                            }
                        )
                    elif i.alert_name == "theft":
                        theft_data.append(
                            {
                                "x": epoch_milliseconds(i.epoch_time),
                                "y": round(i.fuel_consumption, 2),
                            }
                        )
            refuel_final_data = {
                "name": "Refuel",
                "data": refuel_data,
                "type": "column",
            }
            theft_final_data = {
                "name": "Fuel Drain",
                "data": theft_data,
                "type": "column",
            }
            dg_unit_final_data = {
                "name": "DG_Unit_Consumption",
                "data": dg_unit_data,
                "type": "column",
            }
            dg_fuel_final_data = {
                "name": "DG_Fuel_Consumed",
                "data": dg_fuel_data,
                "type": "column",
            }
            dg_unit_per_litre_data = {
                "name": "Dg_Unit_Per_Ltr",
                "data": dg_unit_per_litre,
                "type": "column",
            }
            return Response(
                {
                    "status": 200,
                    "provider_status": "OK",
                    "fuel_level": {
                        "name": "Fuel Level",
                        "data": final_data,
                        "type": "column",
                    },
                    "data": final_data,
                    "refuel_alert": refuel_final_data,
                    "theft_alert": theft_final_data,
                    "dg_unit_data": dg_unit_final_data,
                    "dg_fuel_data": dg_fuel_final_data,
                    "dg_fuel_consumed": dg_fuel_final_data,
                    "dg_unit_per_litre_data": dg_unit_per_litre_data,
                    "dg_unit_per_litre": dg_unit_per_litre_data,
                }
            )
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})


class DgFuelConsumptionDataCustomRangeApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            from_date = data.get("from_date")
            end_date = data.get("end_date")
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%Y-%m-%d")
            site = Site.objects.get(id=site_id)
            final_data = DgFuelConsumptionDataApi_new._fuel_level_series_for_range(
                site, from_date.date(), end_date.date()
            )
            dg_data = _dg_fuel_queryset(DgUnitConsumption.objects).filter(
                site=site_id,
                created__date__gte=from_date.date(),
                created__date__lte=end_date.date(),
            )
            logger.debug(final_data)
            logger.debug(dg_data)
            logger.debug("%s %s", "dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: %s", i)
                    unit_consumption = getattr(i, "unit_consumption", None)
                    dg_fuel_consumption = getattr(i, "dg_fuel_consumption", None)
                    epoch_ms = epoch_milliseconds(getattr(i, "epoch_time", None))
                    if (
                        unit_consumption is None
                        or dg_fuel_consumption is None
                        or epoch_ms is None
                        or float(unit_consumption) < 1
                    ):
                        continue
                    dg_unit_data.append(
                        {"x": epoch_ms, "y": round(unit_consumption, 2)}
                    )
                    dg_fuel_data.append(
                        {"x": epoch_ms, "y": round(dg_fuel_consumption, 2)}
                    )
                    if dg_fuel_consumption > 0:
                        dg_unit_per_litre.append(
                            {
                                "x": epoch_ms,
                                "y": round(unit_consumption / dg_fuel_consumption, 2),
                            }
                        )
            refuel_data = []
            theft_data = []
            fuel_alerts = (
                _dg_fuel_queryset(DGFuelAlertsData.objects)
                .filter(
                    site=site_id,
                    created__date__gte=from_date.date(),
                    created__date__lte=end_date.date(),
                )
                .order_by("created")
            )
            if fuel_alerts.exists():
                for i in fuel_alerts:
                    if i.alert_name == "refuel":
                        refuel_data.append(
                            {
                                "x": epoch_milliseconds(i.epoch_time),
                                "y": round(i.fuel_consumption, 2),
                            }
                        )
                    elif i.alert_name == "theft":
                        theft_data.append(
                            {
                                "x": epoch_milliseconds(i.epoch_time),
                                "y": round(i.fuel_consumption, 2),
                            }
                        )

            refuel_final_data = {
                "name": "Refuel",
                "data": refuel_data,
                "type": "column",
            }
            theft_final_data = {
                "name": "Fuel Drain",
                "data": theft_data,
                "type": "column",
            }
            dg_unit_final_data = {
                "name": "DG_Unit_Consumption",
                "data": dg_unit_data,
                "type": "column",
            }
            dg_fuel_final_data = {
                "name": "DG_Fuel_Consumed",
                "data": dg_fuel_data,
                "type": "column",
            }
            dg_unit_per_litre_data = {
                "name": "Dg_Unit_Per_Ltr",
                "data": dg_unit_per_litre,
                "type": "column",
            }
            return Response(
                {
                    "status": 200,
                    "data": final_data,
                    "refuel_alert": refuel_final_data,
                    "theft_alert": theft_final_data,
                    "dg_unit_data": dg_unit_final_data,
                    "dg_fuel_data": dg_fuel_final_data,
                    "dg_fuel_consumed": dg_fuel_final_data,
                    "dg_unit_per_litre_data": dg_unit_per_litre_data,
                    "dg_unit_per_litre": dg_unit_per_litre_data,
                }
            )
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})


def DGfuelMonthlyTrendMultipleAisles(site_id):
    try:
        # data = request.data
        # site_id = data.get("site_id")
        aisle_groups = AisleGroup.objects.filter(site=int(site_id))

        # Separate mains and DG aisles into separate lists
        mains_aisles = []
        dg_aisles = []

        for aisle in aisle_groups:
            if aisle.power_source == 0:  # Mains
                mains_aisles.append(aisle.attached_leg_id)
            elif aisle.power_source == 1:  # DG
                dg_aisles.append(aisle.attached_leg_id)

        if not mains_aisles and not dg_aisles:
            return Response(
                {"status": 400, "msg": "No matching aisles found for the site."}
            )

        # Prepare lists to store data for each month
        current_date = datetime.now().replace(day=15)
        dg_fuel_consumption_list = []
        mains_unit_consumption_list = []
        dg_unit_consumption_list = []
        month_list = []

        # Iterate over the last 12 months
        for i in range(11, -1, -1):
            month = current_date - timedelta(days=int(i * 365 / 12))
            date_in_str = month.strftime("%b")
            year_in_str = month.strftime("%Y")
            modified_date = f"{date_in_str}-{year_in_str}"
            month_list.append(modified_date)

            # Fuel data for the month
            fuel_data = (
                _dg_fuel_queryset(DgFuelConsumptionData.objects)
                .filter(
                    site=site_id, created__year=month.year, created__month=month.month
                )
                .order_by("created")
            )

            dg_fuel_alert_data = (
                _dg_fuel_queryset(DGFuelAlertsData.objects)
                .filter(
                    site=site_id,
                    created__year=month.year,
                    created__month=month.month,
                    alert_name="refuel",
                )
                .aggregate(Sum("fuel_consumption"))
            )

            # Calculate DG fuel consumption
            refuel_value = dg_fuel_alert_data["fuel_consumption__sum"] or 0
            initial_fuel_value = 0
            last_fuel_value = 0
            if fuel_data.exists():
                first_entry = fuel_data[0]
                initial_fuel_value = first_entry.fuel_consumption
                last_entry = fuel_data.last()
                last_fuel_value = last_entry.fuel_consumption

            total_dg_fuel_consumed = initial_fuel_value + refuel_value - last_fuel_value
            total_dg_fuel_consumed = max(total_dg_fuel_consumed, 0)
            dg_fuel_consumption_list.append(round(total_dg_fuel_consumed, 2))

            # Calculate mains unit consumption
            total_mains_unit_consumed = (
                DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group__in=mains_aisles,
                    reading_for__year=month.year,
                    reading_for__month=month.month,
                ).aggregate(Sum("unit_consumption"))["unit_consumption__sum"]
                or 0
            )

            # Calculate DG unit consumption
            total_dg_unit_consumed = (
                DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group__in=dg_aisles,
                    reading_for__year=month.year,
                    reading_for__month=month.month,
                ).aggregate(Sum("unit_consumption"))["unit_consumption__sum"]
                or 0
            )

            # Append values to their respective lists
            mains_unit_consumption_list.append(round(total_mains_unit_consumed, 2))
            dg_unit_consumption_list.append(round(total_dg_unit_consumed, 2))

        return Response(
            {
                "status": 200,
                "test_arg": "Hello World",
                "months": month_list,
                "dg_fuel_monthly": dg_fuel_consumption_list,
                "mains_unit_consumption_monthly": mains_unit_consumption_list,
                "dg_unit_consumption_monthly": dg_unit_consumption_list,
            }
        )
    except Exception as err:
        return Response({"status": 500, "msg": str(err)})


class DgFuelMonthlyTrend(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")
            if site_id == int(124):
                logger.debug("%s", "inside 124 condition")
                return DGfuelMonthlyTrendMultipleAisles(124)
            aisle_group = AisleGroup.objects.filter(site=site_id)
            mains_aisle = 0
            dg_aisle = 0
            for aisle in aisle_group:
                if aisle.power_source == 0:
                    mains_aisle = aisle.attached_leg_id
                elif aisle.power_source == 1:
                    dg_aisle = aisle.attached_leg_id
            if not mains_aisle and not dg_aisle:
                return Response({"status": 400, "msg": "aisle not matched"})
            current_date = datetime.now().replace(day=15)
            dg_fuel_consumption_list = []
            mains_unit_consumption_list = []
            dg_unit_consumption_list = []
            month_list = []
            for i in range(11, -1, -1):
                month = current_date - timedelta(days=int(i * 365 / 12))
                logger.debug("%s %s", "month##### : ", month.date())
                date_in_str = month.strftime("%b")
                year_in_str = month.strftime("%Y")
                modified_date = date_in_str + "-" + year_in_str
                month_list.append(modified_date)
                start_date = (
                    datetime.now()
                    .date()
                    .replace(
                        year=datetime.now().year - 1,
                        month=datetime.now().month % 12 + 1,
                        day=1,
                    )
                )
                fuel = list(
                    _dg_fuel_queryset(DgUnitConsumption.objects)
                    .filter(
                        site_id=site_id,
                        created__range=(start_date, datetime.now().date()),
                    )
                    .annotate(month=TruncMonth("created"))
                    .values("month")
                    .annotate(total_units=Sum("dg_fuel_consumption"))
                    .order_by("month")
                    .values_list("total_units", flat=True)
                )
                fuel_data = (
                    _dg_fuel_queryset(DgFuelConsumptionData.objects)
                    .filter(
                        site=site_id,
                        created__year=month.year,
                        created__month=month.month,
                    )
                    .order_by("created")
                )
                dg_fuel_alert_data = (
                    _dg_fuel_queryset(DGFuelAlertsData.objects)
                    .filter(
                        site=site_id,
                        created__year=month.year,
                        created__month=month.month,
                        alert_name="refuel",
                    )
                    .aggregate(Sum("fuel_consumption"))
                )
                refuel_value = 0
                dg_fuel_alert_data = dg_fuel_alert_data["fuel_consumption__sum"]
                if dg_fuel_alert_data is not None:
                    refuel_value = dg_fuel_alert_data
                initial_fuel_value = 0
                last_fuel_value = 0
                if fuel_data.exists():
                    first_entry = fuel_data[0]
                    initial_fuel_value = first_entry.fuel_consumption
                    last_entry = fuel_data.last()
                    last_fuel_value = last_entry.fuel_consumption
                total_dg_fuel_consumed = (
                    initial_fuel_value + refuel_value - last_fuel_value
                )
                if total_dg_fuel_consumed < 0:
                    total_dg_fuel_consumed = 0
                dg_fuel_consumption_list.append(round(total_dg_fuel_consumed, 2))
                mains_unit_consumed = DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group=mains_aisle,
                    reading_for__year=month.year,
                    reading_for__month=month.month,
                ).aggregate(Sum("unit_consumption"))
                dg_unit_consumed = DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group=dg_aisle,
                    reading_for__year=month.year,
                    reading_for__month=month.month,
                ).aggregate(Sum("unit_consumption"))
                mains_unit_consumed = mains_unit_consumed["unit_consumption__sum"]
                dg_unit_consumed = dg_unit_consumed["unit_consumption__sum"]
                if mains_unit_consumed is not None:
                    mains_unit = mains_unit_consumed
                else:
                    mains_unit = 0
                if dg_unit_consumed is not None:
                    dg_unit = dg_unit_consumed
                else:
                    dg_unit = 0
                mains_unit_consumption_list.append(round(mains_unit, 2))
                dg_unit_consumption_list.append(round(dg_unit, 2))
            return Response(
                {
                    "status": 200,
                    "test_Args": ["Not the 124"],
                    "months": month_list,
                    "dg_fuel_monthly": fuel,
                    "mains_unit_consumption_monthly": mains_unit_consumption_list,
                    "dg_unit_consumption_monthly": dg_unit_consumption_list,
                }
            )
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class DgFuelConsumptionDataApiUsingLoconavAPI_new(APIView):
    """
    This API is used to get the DG fuel consumption data for a site on a given date. Uses the Loconav Push API for the process.
    """

    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            date_str = data.get("date")
            download_excel = data.get("download_excel", False)

            if not site_id or not date_str:
                return Response({"status": 400, "msg": "site_id and date are required"})

            site = Site.objects.get(id=site_id)
            selected_date = datetime.strptime(date_str, "%Y/%m/%d").date()
            vehical_number = (
                site.partner_dg_fuel_id.upper() if site.partner_dg_fuel_id else ""
            )

            provider_status = DgFuelConsumptionDataApi_new._get_provider_status(
                site, selected_date
            )
            if provider_status == "SUBSCRIPTION_EXPIRED":
                return Response(DgFuelConsumptionDataApi_new._expired_graph_response())

            # 1. Fetch Fuel Consumption Data
            final_data = DgFuelConsumptionDataApi_new._fuel_level_series_for_day(
                site, selected_date, provider_status=provider_status
            )

            # 2. Fetch DG Unit Consumption Data
            dg_qs = (
                _dg_fuel_queryset(DgUnitConsumption.objects)
                .filter(site=site_id, created__date=selected_date)
                .values(
                    "epoch_time",
                    "unit_consumption",
                    "dg_fuel_consumption",
                    "fetch_fuel_data",
                    "created",
                    "dg_end_date",
                    "dg_start_date",
                )
            )

            dg_unit_data, dg_fuel_data, dg_unit_per_litre = [], [], []
            for i in dg_qs:
                if (
                    i["unit_consumption"] is None
                    or i["dg_fuel_consumption"] is None
                    or i.get("fetch_fuel_data", False)
                ):
                    continue
                u_cons = i["unit_consumption"]
                f_cons = i["dg_fuel_consumption"]
                base_epoch_ms = DgFuelConsumptionDataApi_new._dg_graph_base_time(i)
                if base_epoch_ms is None:
                    continue

                if float(u_cons) < 1:
                    continue

                dg_unit_data.append({"x": base_epoch_ms, "y": round(u_cons, 2)})
                dg_fuel_data.append(
                    {
                        "x": DgFuelConsumptionDataApi_new._graph_epoch_ms(
                            base_epoch_ms, 1
                        ),
                        "y": round(f_cons, 2),
                    }
                )
                if f_cons > 0:
                    dg_unit_per_litre.append(
                        {
                            "x": DgFuelConsumptionDataApi_new._graph_epoch_ms(
                                base_epoch_ms, 3
                            ),
                            "y": round(u_cons / f_cons, 2),
                        }
                    )

            refuel_data, theft_data = (
                DgFuelConsumptionDataApi_new._normalized_alert_series(
                    site_id,
                    selected_date,
                    selected_date,
                )
            )

            response_payload = {
                "status": 200,
                "provider_status": provider_status,
                "data": final_data,
                "refuel_alert": {
                    "name": "Refuel",
                    "data": refuel_data,
                    "type": "column",
                },
                "theft_alert": {
                    "name": "Fuel Drain",
                    "data": theft_data,
                    "type": "column",
                },
                "dg_unit_data": {
                    "name": "DG_Unit_Consumption",
                    "data": dg_unit_data,
                    "type": "column",
                },
                "dg_fuel_data": {
                    "name": "DG_Fuel_Consumed",
                    "data": dg_fuel_data,
                    "type": "column",
                },
                "dg_fuel_consumed": {
                    "name": "DG_Fuel_Consumed",
                    "data": dg_fuel_data,
                    "type": "column",
                },
                "dg_unit_per_litre_data": {
                    "name": "Dg_Unit_Per_Ltr",
                    "data": dg_unit_per_litre,
                    "type": "column",
                },
                "dg_unit_per_litre": {
                    "name": "Dg_Unit_Per_Ltr",
                    "data": dg_unit_per_litre,
                    "type": "column",
                },
            }

            if download_excel:
                # Prepare Excel data
                fuel_level_df = pd.DataFrame(
                    [
                        {
                            "Date": datetime.fromtimestamp(i["x"] / 1000).strftime(
                                "%d-%b-%Y"
                            ),
                            "Time": datetime.fromtimestamp(i["x"] / 1000).strftime(
                                "%H:%M"
                            ),
                            "Fuel_Level": i["y"],
                        }
                        for i in final_data
                    ],
                    columns=["Date", "Time", "Fuel_Level"],
                )

                dg_cons_df = pd.DataFrame(
                    [
                        {
                            "Time": datetime.fromtimestamp(i["x"] / 1000).strftime(
                                "%H:%M"
                            ),
                            "Unit_Consumption(KWH)": i["y"],
                            "Fuel_Consumed(Ltr)": next(
                                (f["y"] for f in dg_fuel_data if f["x"] == i["x"]), 0
                            ),
                        }
                        for i in dg_unit_data
                    ],
                    columns=["Time", "Unit_Consumption(KWH)", "Fuel_Consumed(Ltr)"],
                )

                alerts_data = []
                for r in refuel_data:
                    alerts_data.append(
                        {
                            "Time": datetime.fromtimestamp(r["x"] / 1000).strftime(
                                "%H:%M"
                            ),
                            "Activity": "Refuel",
                            "Amount(Ltr)": r["y"],
                        }
                    )
                for t in theft_data:
                    alerts_data.append(
                        {
                            "Time": datetime.fromtimestamp(t["x"] / 1000).strftime(
                                "%H:%M"
                            ),
                            "Activity": "Drain",
                            "Amount(Ltr)": t["y"],
                        }
                    )
                alerts_df = pd.DataFrame(
                    alerts_data, columns=["Time", "Activity", "Amount(Ltr)"]
                )

                io_buffer = BytesIO()
                with pd.ExcelWriter(io_buffer, engine="xlsxwriter") as writer:
                    fuel_level_df.to_excel(writer, sheet_name="Fuel Level", index=False)
                    dg_cons_df.to_excel(writer, sheet_name="Consumption", index=False)
                    alerts_df.to_excel(writer, sheet_name="Alerts", index=False)

                response = HttpResponse(
                    io_buffer.getvalue(),
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                filename = f"DG_Fuel_Report_{site.site_name.replace(' ', '_')}_{date_str.replace('/', '-')}.xlsx"
                response["Content-Disposition"] = f"attachment; filename={filename}"
                return response

            return Response(response_payload)

        except Exception as err:
            import traceback

            traceback.print_exc()
            return Response({"status": 500, "data": [], "error": str(err)})


class DgFuelConsumptionDataCustomRangeApiUsingPushAPIs(APIView):
    permission_classes = [AllowAny]

    @staticmethod
    def _normalized_alert_series(site_id, start_date, end_date):
        return DgFuelConsumptionDataApi_new._normalized_alert_series(
            site_id, start_date, end_date
        )

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            from_date = data.get("from_date")
            end_date = data.get("end_date")
            site = Site.objects.get(id=site_id)
            vehical_number = site.partner_dg_fuel_id.upper()
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%Y-%m-%d")
            provider_status = DgFuelConsumptionDataApi_new._get_provider_status(
                site, from_date.date()
            )
            if provider_status == "SUBSCRIPTION_EXPIRED":
                return Response(DgFuelConsumptionDataApi_new._expired_graph_response())
            final_data = DgFuelConsumptionDataApi_new._fuel_level_series_for_range(
                site, from_date.date(), end_date.date()
            )
            dg_data = _dg_fuel_queryset(DgUnitConsumption.objects).filter(
                site=site_id,
                created__date__gte=from_date.date(),
                created__date__lte=end_date.date(),
            )
            logger.debug(final_data)
            logger.debug(dg_data)
            logger.debug("%s %s", "dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: %s", i)
                    if DgFuelConsumptionDataApi_new._row_value(
                        i, "fetch_fuel_data", False
                    ):
                        continue
                    unit_consumption = DgFuelConsumptionDataApi_new._row_value(
                        i, "unit_consumption"
                    )
                    dg_fuel_consumption = DgFuelConsumptionDataApi_new._row_value(
                        i, "dg_fuel_consumption"
                    )
                    if unit_consumption is None or dg_fuel_consumption is None:
                        continue
                    unit_consumption = float(unit_consumption)
                    dg_fuel_consumption = float(dg_fuel_consumption)
                    if unit_consumption < 1:
                        continue
                    base_epoch_ms = DgFuelConsumptionDataApi_new._dg_graph_base_time(i)
                    if base_epoch_ms is None:
                        continue
                    dg_unit_data.append(
                        {"x": base_epoch_ms, "y": round(unit_consumption, 2)}
                    )
                    dg_fuel_data.append(
                        {
                            "x": DgFuelConsumptionDataApi_new._graph_epoch_ms(
                                base_epoch_ms, 1
                            ),
                            "y": round(dg_fuel_consumption, 2),
                        }
                    )
                    if dg_fuel_consumption > 0:
                        dg_unit_per_litre.append(
                            {
                                "x": DgFuelConsumptionDataApi_new._graph_epoch_ms(
                                    base_epoch_ms, 3
                                ),
                                "y": round(unit_consumption / dg_fuel_consumption, 2),
                            }
                        )
            refuel_data, theft_data = self._normalized_alert_series(
                site_id,
                from_date.date(),
                end_date.date(),
            )

            refuel_final_data = {
                "name": "Refuel",
                "data": refuel_data,
                "type": "column",
            }
            theft_final_data = {
                "name": "Fuel Drain",
                "data": theft_data,
                "type": "column",
            }
            dg_unit_final_data = {
                "name": "DG_Unit_Consumption",
                "data": dg_unit_data,
                "type": "column",
            }
            dg_fuel_final_data = {
                "name": "DG_Fuel_Consumed",
                "data": dg_fuel_data,
                "type": "column",
            }
            dg_unit_per_litre_data = {
                "name": "Dg_Unit_Per_Ltr",
                "data": dg_unit_per_litre,
                "type": "column",
            }
            return Response(
                {
                    "status": 200,
                    "provider_status": provider_status,
                    "fuel_level": {
                        "name": "Fuel Level",
                        "data": final_data,
                        "type": "column",
                    },
                    "data": final_data,
                    "refuel_alert": refuel_final_data,
                    "theft_alert": theft_final_data,
                    "dg_unit_data": dg_unit_final_data,
                    "dg_fuel_data": dg_fuel_final_data,
                    "dg_fuel_consumed": dg_fuel_final_data,
                    "dg_unit_per_litre_data": dg_unit_per_litre_data,
                    "dg_unit_per_litre": dg_unit_per_litre_data,
                }
            )
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})


class DgAlertsPushInterface(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            interface_id = request.headers.get("X-Interface-Id")
            map_of_interfaces = {
                "Roadcaste": "ARGNDG390021",
                "AviconnTesting": "172290",
            }
            if interface_id not in map_of_interfaces.values():
                raise AttributeError(
                    "Invalid Interface ID, the Data can't be processed"
                )
            data = request.data
            DGAlertsData.objects.create(alert_data=data)
            return Response({"status": 200, "message": "DG Fuel Alert Recieved"})
        except AttributeError as e:
            return Response({"message": str(e), "status": 400})
        except Exception as e:
            return Response({"message": str(e), "status": 500})


class DGFuelDataExcelExport(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")
            site = Site.objects.get(id=site_id)
            from_date = datetime.strptime(data.get("start_date"), "%Y-%m-%d")
            end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")
            vehical_number = site.partner_dg_fuel_id.upper()

            dg_fuel_values = (
                _dg_fuel_queryset(DgFuelConsumptionData.objects)
                .filter(site=site_id, created__date__range=(from_date, end_date))
                .annotate(minute_bucket=TruncMinute("created"))
                .values("minute_bucket")
                .annotate(Fuel_Level=Avg("fuel_consumption"))
                .order_by("-minute_bucket")
            )

            fuel_absolute_data = [
                {
                    "Date": i["minute_bucket"].strftime("%d-%b-%Y"),
                    "Time": i["minute_bucket"].strftime("%H:%M"),
                    "Fuel_Level": (
                        round(i["Fuel_Level"], 2) if i["Fuel_Level"] is not None else 0
                    ),
                }
                for i in dg_fuel_values
            ]

            dg_data = (
                _dg_fuel_queryset(DgUnitConsumption.objects)
                .filter(
                    site=site_id,
                    created__date__range=(from_date.date(), end_date.date()),
                )
                .order_by("-created")
            )
            dg_fuel_unit_data = [
                {
                    "Start_Date": i.dg_start_date.strftime("%d-%b-%Y"),
                    "Start_Time": i.dg_start_date.strftime("%H:%M"),
                    "End_Date": i.dg_end_date.strftime("%d-%b-%Y"),
                    "End_Time": i.dg_end_date.strftime("%H:%M"),
                    "DG_Fuel_Consumed(Litres)": i.dg_fuel_consumption,
                    "DG_Unit_Consumption(KWH)": i.unit_consumption,
                    "DG_Unit_Per_Ltr": (
                        round(i.unit_consumption / i.dg_fuel_consumption, 2)
                        if i.dg_fuel_consumption > 0
                        else 0
                    ),
                }
                for i in dg_data
            ]

            alerts = DGAlertsData.objects.filter(
                Q(alert_data__contains=vehical_number),
                Q(created__date__range=(from_date.date(), end_date.date())),
            )

            refuel_theft_data = [
                {
                    "Date": datetime.strptime(
                        i.get("event_time", i.get("dateTimeStamp")[:-6]),
                        "%Y-%m-%dT%H:%M:%S.%f",
                    ).strftime("%d-%b-%Y"),
                    "Time": datetime.strptime(
                        i.get("event_time", i.get("dateTimeStamp")[:-6]),
                        "%Y-%m-%dT%H:%M:%S.%f",
                    ).strftime("%H:%M"),
                    "Activity": (
                        "Refuel"
                        if i.get("alert_type", i.get("eventType"))
                        in ["RefuelingAlert", "deviceFuelFill"]
                        else "Theft"
                    ),
                    "Fuel(in Litres)": round(
                        float(
                            i.get(
                                "refueled_in_liters",
                                i.get("fuelChange").split("ltr")[0],
                            )
                        ),
                        2,
                    ),
                }
                for i in [alert.alert_data for alert in alerts]
                if i.get("alert_type", i.get("eventType"))
                in ["RefuelingAlert", "theft", "deviceFuelDrop", "deviceFuelFill"]
            ]

            current_date = datetime.now().strftime("%d-%B-%Y")
            io_buffer = BytesIO()
            with pd.ExcelWriter(io_buffer, engine="xlsxwriter") as writer:
                if fuel_absolute_data:
                    pd.DataFrame(fuel_absolute_data).to_excel(
                        writer, sheet_name="Fuel Level", index=False
                    )
                if dg_fuel_unit_data:
                    pd.DataFrame(dg_fuel_unit_data).to_excel(
                        writer, sheet_name="DG Fuel & Unit Consumption", index=False
                    )
                if refuel_theft_data:
                    pd.DataFrame(refuel_theft_data).to_excel(
                        writer, sheet_name="DG Refuel & Theft Data", index=False
                    )

            response = HttpResponse(
                io_buffer.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = (
                f"attachment; filename=Report_DG_Fuel_Unit_Trend_{current_date}.xlsx"
            )
            return response

        except Exception as err:
            import traceback

            traceback.print_exc()
            return Response({"status": 500, "msg": str(err)})


class DgFuelMonthlyTrend_test(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")

            # Special case: site_id 124
            if site_id == int(124):
                return DGfuelMonthlyTrendMultipleAisles(124)

            # Find mains and DG aisles
            aisle_group = AisleGroup.objects.filter(site=site_id)
            mains_aisle, dg_aisle = 0, 0
            for aisle in aisle_group:
                if aisle.power_source == 0:
                    mains_aisle = aisle.attached_leg_id
                elif aisle.power_source == 1:
                    dg_aisle = aisle.attached_leg_id

            if not mains_aisle and not dg_aisle:
                return Response({"status": 400, "msg": "aisle not matched"})

            # Build month list for last 12 months
            current_date = datetime.now().replace(day=1)
            month_list = [
                (current_date - relativedelta(months=i)) for i in range(11, -1, -1)
            ]
            month_labels = [m.strftime("%b-%Y") for m in month_list]

            # ---- Fetch data in bulk ----
            start_date = month_list[0].replace(day=1)
            end_date = current_date + relativedelta(months=1)  # exclusive upper bound

            # DG fuel consumption (from DgUnitConsumption)
            dg_fuel_raw = (
                _dg_fuel_queryset(DgUnitConsumption.objects)
                .filter(site_id=site_id, created__gte=start_date, created__lt=end_date)
                .annotate(month=TruncMonth("created"))
                .values("month")
                .annotate(total=Sum("dg_fuel_consumption"))
                .order_by("month")
            )
            """dg_fuel_raw = (
                DgFuelConsumptionData.objects
             .filter(
                site_id=site_id,
                created__gte=start_date,
                created__lt=end_date
                )
            .annotate(month=TruncMonth("created"))
            .values("month")
            .annotate(total=Sum("fuel_consumption"))
             .order_by("month")
            )"""
            dg_fuel_map = {
                row["month"].strftime("%b-%Y"): row["total"] or 0 for row in dg_fuel_raw
            }

            # Mains unit consumption
            mains_units_raw = (
                DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group=mains_aisle,
                    reading_for__gte=start_date,
                    reading_for__lt=end_date,
                )
                .annotate(month=TruncMonth("reading_for"))
                .values("month")
                .annotate(total=Sum("unit_consumption"))
                .order_by("month")
            )
            mains_units_map = {
                row["month"].strftime("%b-%Y"): row["total"] or 0
                for row in mains_units_raw
            }

            # DG unit consumption
            dg_units_raw = (
                DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group=dg_aisle,
                    reading_for__gte=start_date,
                    reading_for__lt=end_date,
                )
                .annotate(month=TruncMonth("reading_for"))
                .values("month")
                .annotate(total=Sum("unit_consumption"))
                .order_by("month")
            )
            dg_units_map = {
                row["month"].strftime("%b-%Y"): row["total"] or 0
                for row in dg_units_raw
            }

            # ---- Build final aligned lists ----
            dg_fuel_consumption_list = [
                round(dg_fuel_map.get(label, 0), 2) for label in month_labels
            ]
            mains_unit_consumption_list = [
                round(mains_units_map.get(label, 0), 2) for label in month_labels
            ]
            dg_unit_consumption_list = [
                round(dg_units_map.get(label, 0), 2) for label in month_labels
            ]

            return Response(
                {
                    "status": 200,
                    "months": month_labels,
                    "dg_fuel_monthly": dg_fuel_consumption_list,
                    "mains_unit_consumption_monthly": mains_unit_consumption_list,
                    "dg_unit_consumption_monthly": dg_unit_consumption_list,
                }
            )

        except Exception as err:
            return Response({"status": 500, "msg": str(err)})
