"""Energy-saving charts, trends, snapshots and Excel exports."""

import time
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
from django.db.models import Q, Sum
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    DailySiteReading,
    HourlySiteReading,
    Site,
    SiteBaseline,
)
from wareApp.utility import entryExit, logger


class ParticularSiteSnapshotEnergySavingApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        # print("data of site snapshot", data)
        site_id = data.get("site_id", "")
        # print("site id is: ", site_id)
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        carbon_visible = False
        carbon_emission_value = 0
        if site.is_carbon_emission_visible:
            carbon_emission_value = site.carbon_emission_value
            carbon_visible = True
        live_date = site.live_date
        # print("live_date :",live_date)
        user_type = data.get("user_type")
        # print("site data", site)
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        previous = datetime.strftime(previous_date, "%d-%b-%Y")
        if int(data.get("site_id", "")) == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023)
        else:
            baseline_date = site.baseline_date.date()
        date = datetime.strftime(baseline_date, "%d-%b-%Y")
        alarm = AlarmNotifications.objects.filter(site_id=site, user_level=4).count()
        # print("alarm count on site page: ", alarm)
        # daily = DailySiteReading.objects.filter(associated_Site=site)
        if site.live_date:
            # print("inside live date if condition: ")
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_id,
                    reading_for__gte=baseline_date,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )

            else:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_id,
                    reading_for__gte=baseline_date,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )
                live_date = site.live_date
                live_date = datetime.strftime(live_date, "%Y/%m/%d")

        else:
            # print("inside else condition. site is not live")
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=site,
                    reading_for__gte=baseline_date,
                    leg_id__in=all_leg_id,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )
            else:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=site,
                    reading_for__lte=previous_date,
                    reading_for__gte=baseline_date,
                    leg_id__in=all_leg_id,
                )
                live_date = "Not Live yet"
        energyConsumed = 0.0
        energySaved = 0.0
        carbon_saved = 0.0

        for i in daily:
            # print("inside for loop!!!!")
            energyConsumed += i.unit_consumption
            # if i.energy_saved >= 0:
            energySaved += i.daily_baseline_value
        energySaved = energySaved - energyConsumed
        if carbon_visible:
            carbon_saved = energySaved * carbon_emission_value
        try:
            percentageSaved = (
                str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
            )
            # live_date = site.live_date
            # live_date = datetime.strftime(live_date, "%Y/%m/%d")
        except Exception as e:
            logger.debug("%s %s", "exception is", e)
            percentageSaved = str(0.0) + " %"
        return Response(
            {
                "result": 1,
                "alarms": alarm,
                "energy_consumed": str(round(energyConsumed, 1)),
                "saved_energy": str(round(energySaved, 1)),
                "carbon_emission_saved": str(round(carbon_saved, 1)),
                "percentage_saved": percentageSaved,
                "live_date": date,
                "previous_date": previous,
                "site_live_date": live_date,
            }
        )


class EnergySavingMonthlyBarChartOld(APIView):
    @entryExit
    def post(self, request):
        t1 = time.time()
        data = request.data
        site_id = data.get("site_id", "")
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        live_date = site.live_date
        previous_date = live_date - timedelta(days=1)
        from_date = data.get("from_date", "")
        till_date = data.get("till_date", "")
        user_type = int(data.get("user_type", ""))
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        currentDate = datetime.now()
        dateList = []
        dataList = []
        savingDataList = []
        if tillDate.month == currentDate.month:
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
            for aisle in aisle_group:
                leg = aisle.attached_leg_id
                dateList = []
                unitConsumptionList = []
                savingConsumptionList = []
                daily_data = DailySiteReading.objects.filter(
                    associated_Site=site, leg_id=leg, is_visible=True
                )
                for i in range(30):
                    date = tillDate - timedelta(days=29 - i)
                    dateList.append(date.date())
                    unit_consumption = 0.0
                    energy_saved = 0.0
                    if currentDate.date() == date.date():
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
                                unit_consumption += k.unit_consumption
                                energy_saved += k.energy_saved
                        unitConsumptionList.append(round(unit_consumption, 2))
                        savingConsumptionList.append(round(energy_saved, 2))
                    else:
                        if user_type in [4, 5] and previous_date.date() < date.date():
                            daily = daily_data.filter(reading_for=date)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                                    energy_saved += j.energy_saved
                            unitConsumptionList.append(round(unit_consumption, 2))
                            savingConsumptionList.append(round(energy_saved, 2))
                        elif user_type == 1:
                            daily = daily_data.filter(reading_for=date)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                                    energy_saved += j.energy_saved
                            unitConsumptionList.append(round(unit_consumption, 2))
                            savingConsumptionList.append(round(energy_saved, 2))
                        else:
                            unitConsumptionList.append(0)
                            savingConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg
                dataList.append(
                    {"name": name, "data": unitConsumptionList, "type": "column"}
                )
                savingDataList.append(
                    {"name": name, "data": savingConsumptionList, "type": "column"}
                )
            if site.is_live:
                if int(data.get("site_id", "")) == 34:
                    baseline = SiteBaseline.objects.filter(
                        associated_site_id=site_id, leg_id__in=[259, 260, 261, 276]
                    )
                else:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                baselineList = []
                if baseline.exists():
                    if int(data.get("site_id", "")) == 34:
                        latest_baseline_value = SiteBaseline.objects.filter(
                            associated_site_id=site,
                            aisle_group__in=[259, 260, 261, 276],
                        )
                    elif int(data.get("site_id", "")) == 29:
                        latest_baseline_value = SiteBaseline.objects.filter(
                            associated_site_id=29
                        ).exclude(Q(aisle_group__in=[259, 260, 261, 276]))
                    else:
                        latest_baseline_value = SiteBaseline.objects.filter(
                            associated_site_id=site
                        )
                    # latest_baseline_value = latest_baseline_value['baseline_value__sum']
                    for i in range(30):
                        date = tillDate - timedelta(days=29 - i)
                        baseline_value = latest_baseline_value.filter(
                            Q(baseline_to__gte=date.date())
                            | Q(
                                Q(baseline_from__lte=date.date())
                                & Q(baseline_to__isnull=True)
                            )
                        ).aggregate(Sum("baseline_value"))
                        try:
                            baseline_value = baseline_value["baseline_value__sum"]
                            if baseline_value is not None:
                                baselineList.append(round(baseline_value, 2))
                            else:
                                baselineList.append(0)
                        except Exception as e:
                            logger.debug("%s %s", "Exception 1 is", e)
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                dataList.append(
                    {"name": "baseline", "data": baselineList, "type": "spline"}
                )
        else:
            total_days = (tillDate.day - fromDate.day) + 1
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        site_id=site_id, is_visible=True
                    )
            for aisle in aisle_group:
                leg = aisle.attached_leg_id
                unitConsumptionList = []
                savingConsumptionList = []
                dateList = []
                daily_data = DailySiteReading.objects.filter(
                    associated_Site=site, leg_id=leg, is_visible=True
                )
                for i in range(0, total_days):
                    date = tillDate - timedelta(days=(total_days - 1) - i)
                    dateList.append(date.date())
                    if user_type in [4, 5] and previous_date.date() < date.date():
                        daily = daily_data.filter(reading_for=date)
                        unit_consumption = 0.0
                        energy_saved = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption
                                energy_saved += j.energy_saved

                        unitConsumptionList.append(round(unit_consumption, 2))
                        savingConsumptionList.append(round(energy_saved, 2))
                    elif user_type == 1:
                        daily = daily_data.filter(reading_for=date)
                        unit_consumption = 0.0
                        energy_saved = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption
                                energy_saved += j.energy_saved

                        unitConsumptionList.append(round(unit_consumption, 2))
                        savingConsumptionList.append(round(energy_saved, 2))
                    else:
                        unitConsumptionList.append(0)
                        savingConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg.leg_id
                dataList.append(
                    {"name": name, "data": unitConsumptionList, "type": "column"}
                )
                savingDataList.append(
                    {"name": name, "data": savingConsumptionList, "type": "column"}
                )
            if site.is_live:
                if int(data.get("site_id", "")) == 34:
                    baseline = SiteBaseline.objects.filter(
                        associated_site_id=site_id, leg_id__in=[259, 260, 261, 276]
                    )
                else:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                baselineList = []
                if baseline.exists():
                    if int(data.get("site_id", "")) == 34:
                        latest_baseline_value = SiteBaseline.objects.filter(
                            associated_site_id=site,
                            aisle_group__in=[259, 260, 261, 276],
                        )
                    elif int(data.get("site_id", "")) == 29:
                        latest_baseline_value = SiteBaseline.objects.filter(
                            associated_site_id=29
                        ).exclude(Q(aisle_group__in=[259, 260, 261, 276]))
                    else:
                        latest_baseline_value = SiteBaseline.objects.filter(
                            associated_site_id=site
                        )
                    for i in range(total_days):
                        date = tillDate - timedelta(days=(total_days - 1) - i)
                        baseline_value = latest_baseline_value.filter(
                            Q(baseline_to__gte=date.date())
                            | Q(
                                Q(baseline_from__lte=date.date())
                                & Q(baseline_to__isnull=True)
                            )
                        ).aggregate(Sum("baseline_value"))
                        try:
                            baseline_value = baseline_value["baseline_value__sum"]
                            if baseline_value is not None:
                                baselineList.append(round(baseline_value, 2))
                            else:
                                baselineList.append(0)
                        except Exception as e:
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                            logger.debug("%s %s", "Exception 2 is", e)
                dataList.append(
                    {"name": "baseline", "data": baselineList, "type": "spline"}
                )
        t2 = time.time()
        return Response(
            {
                "result": 1,
                "Dates": dateList,
                "Data": dataList,
                "SavingData": savingDataList,
            }
        )


class EnergySavingMonthlyTrendApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        import hashlib

        from django.core.cache import cache

        data = request.data
        site_id = data.get("site_id", "")
        user_type = data.get("user_type")

        try:
            site_id_int = int(site_id)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid or missing site_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        today_date = datetime.now()
        current_month = today_date.month
        current_year = today_date.year
        current_date = datetime.now().replace(day=15)

        query_site_id = site_id_int
        if site_id_int == 34:
            query_site_id = 29

        try:
            site = Site.objects.get(id=query_site_id)
        except Site.DoesNotExist:
            return Response(
                {"error": "Site not found"}, status=status.HTTP_404_NOT_FOUND
            )

        carbon_visible = False
        carbon_emission_value = 0
        if site.is_carbon_emission_visible:
            carbon_emission_value = site.carbon_emission_value
            carbon_visible = True

        live_date = site.live_date.date()

        if site_id_int == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023).date()
        else:
            baseline_date = site.baseline_date.date()

        baseline_date_str = baseline_date.strftime("%Y-%m-%d")
        current = (today_date - timedelta(days=1)).date()
        live_month_key = live_date.strftime("%Y-%m")

        if site_id_int == 34:
            aisle_group = AisleGroup.objects.filter(
                attached_leg_id__in=[259, 260, 261, 276, 710]
            )
        else:
            aisle_group = AisleGroup.objects.filter(
                virtual_siteID=query_site_id, is_visible=True
            )
        all_leg_id = list(aisle_group.values_list("attached_leg_id", flat=True))

        month_list = []
        energy_consumed_list = []
        carbon_list = []
        energy_saved_list = []
        percentage_saved_list = []

        def month_bounds(reference_date):
            month_start = reference_date.replace(day=1).date()
            if reference_date.month == 12:
                next_month_start = reference_date.replace(
                    year=reference_date.year + 1, month=1, day=1
                ).date()
            else:
                next_month_start = reference_date.replace(
                    month=reference_date.month + 1, day=1
                ).date()
            return month_start, next_month_start

        for i in range(11, -1, -1):
            month = current_date - timedelta(i * 365 / 12)
            month_str = month.strftime("%Y-%m")
            modified_date = month.strftime("%b-%Y")
            month_list.append(modified_date)

            is_current_month = (
                month.month == current_month and month.year == current_year
            )
            cache_key_data = (
                f"energy_monthly_trend:site_{site_id}:user_{user_type}:"
                f"month_{month_str}:baseline_{baseline_date_str}"
            )
            cache_key = hashlib.md5(cache_key_data.encode()).hexdigest()

            if not is_current_month:
                cached_month_data = cache.get(cache_key)
                if cached_month_data:
                    energy_consumed_list.append(cached_month_data["energy_consumed"])
                    energy_saved_list.append(cached_month_data["energy_saved"])
                    carbon_list.append(cached_month_data["carbon_saved"])
                    percentage_saved_list.append(cached_month_data["percentage_saved"])
                    continue

            energy_consumed = 0.0
            energy_saved = 0.0
            carbon_saved = 0.0
            percentage_saved = 0.0

            if month_str >= live_month_key and all_leg_id:
                month_start, next_month_start = month_bounds(month)
                effective_start = max(month_start, baseline_date, live_date)
                effective_end = min(next_month_start - timedelta(days=1), current)

                if effective_start <= effective_end:
                    monthly_totals = DailySiteReading.objects.filter(
                        leg_id__in=all_leg_id,
                        reading_for__gte=effective_start,
                        reading_for__lte=effective_end,
                        is_visible=True,
                    ).aggregate(
                        total_consumed=Sum("unit_consumption"),
                        total_saved=Sum("energy_saved"),
                    )

                    energy_consumed = monthly_totals["total_consumed"] or 0.0
                    energy_saved = monthly_totals["total_saved"] or 0.0

                    if energy_saved < 0:
                        energy_saved = 0.0

                    if carbon_visible and energy_saved > 0:
                        carbon_saved = energy_saved * carbon_emission_value

                    if energy_consumed + energy_saved > 0:
                        percentage_saved = round(
                            energy_saved * 100 / (energy_saved + energy_consumed), 1
                        )

            energy_consumed = round(energy_consumed, 1)
            energy_saved = round(energy_saved, 1)
            carbon_saved = round(carbon_saved, 1)

            energy_consumed_list.append(energy_consumed)
            energy_saved_list.append(energy_saved)
            carbon_list.append(carbon_saved)
            percentage_saved_list.append(percentage_saved)

            if not is_current_month:
                cache.set(
                    cache_key,
                    {
                        "energy_consumed": energy_consumed,
                        "energy_saved": energy_saved,
                        "carbon_saved": carbon_saved,
                        "percentage_saved": percentage_saved,
                    },
                    timeout=60 * 60 * 24 * 90,
                )

        response_data = {
            "result": 1,
            "months": month_list,
            "energySaved": energy_saved_list,
            "energyConsumed": energy_consumed_list,
            "carbon_saved": carbon_list,
            "percentageSaved": percentage_saved_list,
        }

        return Response(response_data)


class EnergySavingMonthlyTrendExcelDownload(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", "")
            from_month = data.get("from_month", "")  # Format: 'YYYY-MM'
            to_month = data.get("to_month", "")  # Format: 'YYYY-MM'
            user_type = data.get("user_type")

            if not site_id or not from_month or not to_month:
                return Response(
                    {
                        "status": 500,
                        "data": [],
                        "msg": "Missing required parameters: site_id, from_month, to_month",
                    }
                )

            if int(site_id) == 34:
                site_id = 29

            # Get site details
            site = Site.objects.get(id=site_id)
            site_name = site.site_name.replace(" ", "_").replace("/", "_")

            carbon_visible = False
            carbon_emission_value = 0
            if site.is_carbon_emission_visible:
                carbon_emission_value = site.carbon_emission_value
                carbon_visible = True

            # Match EnergySavingMonthlyTrendApi baseline date logic exactly
            if int(data.get("site_id", "")) == 34:
                baseline_date = (
                    datetime.now().replace(day=12, month=4, year=2023).date()
                )
            else:
                baseline_date = (
                    site.baseline_date.date()
                    if site.baseline_date
                    else datetime.now().date()
                )

            from_parts = from_month.split("-")
            to_parts = to_month.split("-")

            if len(from_parts) == 2:
                if len(from_parts[0]) == 4:
                    from_year, from_month_num = int(from_parts[0]), int(from_parts[1])
                else:
                    from_month_num, from_year = int(from_parts[0]), int(from_parts[1])
            else:
                return Response(
                    {
                        "status": 500,
                        "data": [],
                        "msg": "Invalid month format. Use YYYY-MM",
                    }
                )

            if len(to_parts) == 2:
                if len(to_parts[0]) == 4:
                    to_year, to_month_num = int(to_parts[0]), int(to_parts[1])
                else:
                    to_month_num, to_year = int(to_parts[0]), int(to_parts[1])
            else:
                return Response(
                    {
                        "status": 500,
                        "data": [],
                        "msg": "Invalid month format. Use YYYY-MM",
                    }
                )

            month_list = []
            energy_consumed_list = []
            carbon_list = []
            energy_saved_list = []
            percentage_saved_list = []
            days_in_month_list = []
            baseline_value_list = []

            # Generate list of months between from_month and to_month
            current_date = datetime.now()
            current = current_date - timedelta(days=1)
            start_date = datetime(from_year, from_month_num, 15)
            end_date = datetime(to_year, to_month_num, 15)

            current_month = start_date

            while current_month <= end_date:
                energyConsumed = 0
                energySaved = 0
                carbon_saved = 0

                date_in_str = current_month.strftime("%b")
                year_in_str = current_month.strftime("%Y")
                modified_date = date_in_str + "-" + year_in_str
                month_list.append(modified_date)

                # Calculate days in current month for display
                import calendar

                days_in_month = calendar.monthrange(
                    current_month.year, current_month.month
                )[1]
                days_in_month_list.append(days_in_month)

                # Match EnergySavingMonthlyTrendApi aisle group logic exactly
                if user_type == 1:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(
                            virtual_siteID=site_id, is_visible=True
                        )
                else:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(
                            virtual_siteID=site_id, is_visible=True
                        )

                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]

                # Match EnergySavingMonthlyTrendApi daily readings filter exactly
                daily = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_id,
                    reading_for__year=current_month.year,
                    reading_for__month=current_month.month,
                    reading_for__gte=baseline_date,
                    reading_for__lte=current.date(),
                    is_visible=True,
                )

                # Match EnergySavingMonthlyTrendApi calculation logic exactly
                if daily.exists():
                    for j in daily:
                        energyConsumed += j.unit_consumption
                        energySaved += j.daily_baseline_value

                # Match EnergySavingMonthlyTrendApi energy saved calculation exactly
                energySaved = energySaved - energyConsumed

                # Calculate carbon saved only if carbon emission is visible for this site
                if carbon_visible:
                    carbon_saved = energySaved * carbon_emission_value

                # Match EnergySavingMonthlyTrendApi percentage calculation exactly
                try:
                    percentage_saved = round(
                        energySaved * 100 / (energySaved + energyConsumed), 1
                    )
                    percentage_saved_list.append(percentage_saved)
                except Exception as e:
                    logger.debug("%s %s", "Exception calculating percentage:", e)
                    percentage_saved_list.append(0.0)

                energy_consumed_list.append(round(energyConsumed, 1))
                energy_saved_list.append(round(energySaved, 1))
                carbon_list.append(round(carbon_saved, 1))
                baseline_value_list.append(
                    round(energySaved + energyConsumed, 1)
                )  # Total baseline = energySaved + energyConsumed

                # Move to next month
                if current_month.month == 12:
                    current_month = current_month.replace(
                        year=current_month.year + 1, month=1
                    )
                else:
                    current_month = current_month.replace(month=current_month.month + 1)

            # Create DataFrame - available for all user types
            if carbon_visible:
                df = pd.DataFrame(
                    {
                        "Month": month_list,
                        "Days in Month": days_in_month_list,
                        "Baseline Value (kWh)": baseline_value_list,
                        "Energy Consumed (kWh)": energy_consumed_list,
                        "Energy Saved (kWh)": energy_saved_list,
                        "Percentage Saved (%)": percentage_saved_list,
                        "Carbon Saved (kg CO2)": carbon_list,
                    }
                )
            else:
                df = pd.DataFrame(
                    {
                        "Month": month_list,
                        "Days in Month": days_in_month_list,
                        "Baseline Value (kWh)": baseline_value_list,
                        "Energy Consumed (kWh)": energy_consumed_list,
                        "Energy Saved (kWh)": energy_saved_list,
                        "Percentage Saved (%)": percentage_saved_list,
                    }
                )

            # Generate filename
            file_name = (
                f"{site_name}_saving_monthly_trend_{from_month}_to_{to_month}.csv"
            )
            response = HttpResponse(content_type="text/csv")
            response["filename"] = file_name
            response["Content-Disposition"] = f"attachment; filename={file_name}"
            df.to_csv(response, index=False)

            return response

        except Site.DoesNotExist:
            return Response({"status": 500, "data": [], "msg": "Site not found"})
        except Exception as err:
            logger.debug(
                "%s %s", "Exception EnergySavingMonthlyTrendExcelDownload:", err
            )
            return Response({"status": 500, "data": [], "msg": str(err)})


class NewEnergySavingMonthlyTrendApi(APIView):
    @entryExit
    def post(self, request):
        try:
            from django.core.cache import cache

            data = request.data
            site_id = data.get("site_id", "")
            user_type = data.get("user_type")

            cache_key = f"energy_monthly_trend:{site_id}:{user_type}"
            cached_prev_data = cache.get(cache_key) or {}

            current_month_key = datetime.now().strftime("%Y-%m")

            current_date = datetime.now().replace(day=15)

            if int(site_id) == 34:
                site_id = 29

            site = Site.objects.get(id=site_id)

            carbon_visible = False
            carbon_emission_value = 0
            if site.is_carbon_emission_visible:
                carbon_emission_value = site.carbon_emission_value
                carbon_visible = True

            live_date = site.live_date.date()

            if int(data.get("site_id", "")) == 34:
                baseline_date = datetime.now().replace(day=12, month=4, year=2023)
            else:
                baseline_date = site.baseline_date.date()

            previous_date = live_date - timedelta(days=1)
            previous_month_year = live_date.strftime("%Y-%m")

            today_date = datetime.now()
            current = today_date - timedelta(days=1)

            month_list = []
            energy_consumed_list = []
            carbon_list = []
            energy_saved_list = []
            percentage_saved_list = []

            if site:
                for i in range(11, -1, -1):
                    month = current_date - timedelta(i * 365 / 12)
                    month_year = month.strftime("%Y-%m")

                    # 🔴 USE REDIS FOR PREVIOUS MONTHS
                    if month_year != current_month_key and cached_prev_data:
                        idx = cached_prev_data["months"].index(
                            month.strftime("%b") + "-" + month.strftime("%Y")
                        )

                        month_list.append(cached_prev_data["months"][idx])
                        energy_consumed_list.append(
                            cached_prev_data["energyConsumed"][idx]
                        )
                        energy_saved_list.append(cached_prev_data["energySaved"][idx])
                        carbon_list.append(cached_prev_data["carbon_saved"][idx])
                        percentage_saved_list.append(
                            cached_prev_data["percentageSaved"][idx]
                        )
                        continue

                    # 🔴 CURRENT MONTH OR CACHE MISS → ORIGINAL LOGIC
                    energyConsumed = 0
                    energySaved = 0
                    carbon_saved = 0

                    date_in_str = month.strftime("%b")
                    year_in_str = month.strftime("%Y")
                    modified_date = date_in_str + "-" + year_in_str
                    month_list.append(modified_date)

                    if previous_month_year <= month_year:

                        if previous_date.month == month.month:

                            if user_type == 1:
                                if int(data.get("site_id")) == 34:
                                    aisle_group = AisleGroup.objects.filter(
                                        attached_leg_id__in=[259, 260, 261, 276, 710]
                                    )
                                else:
                                    aisle_group = AisleGroup.objects.filter(
                                        site_id=site_id, is_visible=True
                                    )
                            else:
                                if int(data.get("site_id")) == 34:
                                    aisle_group = AisleGroup.objects.filter(
                                        attached_leg_id__in=[259, 260, 261, 276, 710]
                                    )
                                else:
                                    aisle_group = AisleGroup.objects.filter(
                                        site_id=site_id, is_visible=True
                                    )

                            all_leg_id = [a.attached_leg_id for a in aisle_group]

                            daily = DailySiteReading.objects.filter(
                                associated_Site=site,
                                leg_id__in=all_leg_id,
                                reading_for__year=month.year,
                                reading_for__month=month.month,
                                reading_for__gte=baseline_date,
                                reading_for__lte=current,
                                is_visible=True,
                            )

                            if daily.exists():
                                for j in daily:
                                    energyConsumed += j.unit_consumption
                                    energySaved += j.daily_baseline_value
                                    if carbon_visible:
                                        carbon_saved = (
                                            energySaved * carbon_emission_value
                                        )

                    energySaved = energySaved - energyConsumed

                    try:
                        percentage_saved = round(
                            energySaved * 100 / (energySaved + energyConsumed), 1
                        )
                    except:
                        percentage_saved = 0.0

                    energy_consumed_list.append(round(energyConsumed, 1))
                    energy_saved_list.append(round(energySaved, 1))
                    carbon_list.append(round(carbon_saved, 1))
                    percentage_saved_list.append(percentage_saved)

            # 🔴 CACHE ONLY PREVIOUS 11 MONTHS
            cache_data = {
                "months": month_list[:-1],
                "energyConsumed": energy_consumed_list[:-1],
                "energySaved": energy_saved_list[:-1],
                "carbon_saved": carbon_list[:-1],
                "percentageSaved": percentage_saved_list[:-1],
            }

            cache.set(cache_key, cache_data, timeout=60 * 60 * 24 * 90)

            return Response(
                {
                    "result": 1,
                    "months": month_list,
                    "energySaved": energy_saved_list,
                    "energyConsumed": energy_consumed_list,
                    "carbon_saved": carbon_list,
                    "percentageSaved": percentage_saved_list,
                }
            )
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class EnergySavingsHourlyBarChartOld(APIView):
    @entryExit
    def post(self, request):
        data = request.data
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
        savingList = []
        all_leg_id = DailySiteReading.objects.filter(
            associated_Site=site, reading_for=date.date()
        ).distinct("leg_id")
        logger.debug("%s %s", "all leg ids", all_leg_id)
        logger.debug("%s %s", "length : ", len(all_leg_id))
        oneDayData = HourlySiteReading.objects.filter(
            associated_Site=site_id, reading_from__date=date.date(), is_visible=True
        )
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
                            energy_saved += j.energy_saved
                        except Exception as e:
                            logger.debug("%s %s", "exception", e)
                unitConsumptionList.append(round(unit_consumption, 2))
                savingConsumptionList.append(round(energy_saved, 2))
            logger.debug("%s %s", "unit data: ", unitConsumptionList)
            # aisle_name = AisleGroup.objects.filter(site=site_id, attached_leg_id=leg.leg_id)
            # if aisle_name.exists():
            #     name = aisle_name[0].aisleGroupName
            # else:
            #     name = leg.leg_id
            dataList.append(
                {"name": name, "data": unitConsumptionList, "type": "column"}
            )
            savingList.append(
                {"name": name, "data": savingConsumptionList, "type": "column"}
            )
        if site.is_live:
            baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
            logger.debug(
                "%s %s", "checking for baseline has been saved or not: ", baseline
            )
            baselineList = []
            if baseline.exists():
                logger.debug("%s %s", "baseline of site is there: ", baseline)
                for i in range(24):
                    current_hour = i
                    if current_hour <= 9:
                        hr = "0" + str(current_hour) + ":00"
                    else:
                        hr = str(current_hour) + ":00"
                    hourList.append(hr)

                    logger.debug(
                        "%s %s", "hour inside baseline calculation", current_hour
                    )
                    try:
                        baseline_value = HourlySiteReading.objects.filter(
                            associated_Site=site,
                            reading_from__hour=current_hour,
                            is_visible=True,
                        )
                        logger.debug(
                            "%s", "checking the baseline value for particular hour"
                        )
                        if baseline_value.exists():
                            logger.debug(
                                "%s %s", "baseline exists for that hour", baseline_value
                            )
                            baseline_data = 0.0
                            for j in baseline_value:
                                baseline_data += j.hourly_baseline_value
                                logger.debug("%s %s", "baseline_data: ", baseline_data)
                            logger.debug(
                                "%s %s", "total baseline of all legs", baseline_data
                            )
                            baselineList.append(baseline_data)
                        else:
                            logger.debug(
                                "%s %s",
                                "baseline doesn't exists for that hour. Sending 0.0 value",
                                baseline_value,
                            )
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                    except Exception as e:
                        logger.debug(
                            "%s %s", "Exception EnergySavingsHourlyBarChart is", e
                        )
                        baseline_value = 0.0
                        baselineList.append(baseline_value)
            dataList.append(
                {"name": "baseline", "data": baselineList, "type": "spline"}
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
        return Response(
            {"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList}
        )


class EnergySavingsHourlyBarChart(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        logger.debug("%s %s", "function start time is: ", start_time)
        site = Site.objects.get(id=site_id)
        date = datetime.strptime(data.get("date", ""), "%Y/%m/%d")
        hourList = ["{:02d}:00".format(i) for i in range(24)]
        dataList = []
        savingList = []
        oneDayData = HourlySiteReading.objects.filter(
            associated_Site=site_id, reading_from__date=date.date(), is_visible=True
        )
        aisle_names = AisleGroup.objects.filter(site=site_id)
        for aisle in aisle_names:
            leg_id = aisle.attached_leg_id
            aisle_name = aisle.aisleGroupName
            unitConsumptionList = []
            savingConsumptionList = []
            hourly_data = (
                oneDayData.filter(Q(leg_id=leg_id))
                .values("reading_from__hour")
                .annotate(
                    unit_consumption_sum=Sum("unit_consumption"),
                    energy_saved_sum=Sum("energy_saved"),
                )
            )
            hourly_data_dict = {
                reading["reading_from__hour"]: reading for reading in hourly_data
            }

            for i in range(24):
                hourly = hourly_data_dict.get(i)
                unit_consumption = (
                    round(hourly["unit_consumption_sum"], 2) if hourly else 0.0
                )
                energy_saved = hourly["energy_saved_sum"] if hourly else 0.0
                unitConsumptionList.append(unit_consumption)
                savingConsumptionList.append(energy_saved)
            dataList.append(
                {"name": aisle_name, "data": unitConsumptionList, "type": "column"}
            )
            savingList.append(
                {"name": aisle_name, "data": savingConsumptionList, "type": "column"}
            )
        if site.is_live:
            latest_baseline_value = (
                SiteBaseline.objects.filter(associated_site_id=site)
                .exclude(Q(baseline_to__isnull=False))
                .aggregate(Sum("baseline_value"))
            )
            latest_baseline_value = latest_baseline_value["baseline_value__sum"]
            if (
                datetime.now().date() == date.date()
                and latest_baseline_value is not None
            ):
                baselineList = [round(latest_baseline_value / 24, 2) for i in range(24)]
            else:
                previousDateDailyBaselineValue = DailySiteReading.objects.filter(
                    associated_Site=site, reading_for=date.date()
                ).aggregate(Sum("daily_baseline_value"))
                previousDateHourlyBaselineValue = previousDateDailyBaselineValue[
                    "daily_baseline_value__sum"
                ]
                if previousDateHourlyBaselineValue is not None:
                    baselineList = [
                        round(previousDateHourlyBaselineValue / 24, 2)
                        for i in range(24)
                    ]
                else:
                    baselineList = [0 for i in range(24)]
            dataList.append(
                {"name": "baseline", "data": baselineList, "type": "spline"}
            )
        end_time = datetime.now()
        logger.debug("%s %s", "function end time is: ", end_time)
        time_taken = end_time - start_time
        logger.debug("%s %s", "time_taken", time_taken)
        return Response(
            {"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList}
        )


class EnergySavingsHourlyBarChartV2(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        logger.debug("%s %s", "function start time is:", start_time)

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"result": 0, "msg": "Site not found"}, status=404)

        date_str = data.get("date", "")
        try:
            date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response({"result": 0, "msg": "Invalid date format"}, status=400)

        hourList = ["{:02d}:00".format(i) for i in range(24)]
        dataList = []
        savingList = []

        all_leg_ids = (
            DailySiteReading.objects.filter(associated_Site=site, reading_for=date)
            .values_list("leg_id", flat=True)
            .distinct()
        )
        logger.debug("%s", all_leg_ids)
        oneDayData = HourlySiteReading.objects.filter(
            associated_Site=site_id, reading_from__date=date, is_visible=True
        ).select_related("aisle_group")
        logger.debug("%s", oneDayData)
        # Group by leg_id and hour to reduce the number of iterations
        hourly_data_map = {
            (item.leg_id, item.reading_from.hour): item for item in oneDayData
        }
        logger.debug("%s", hourly_data_map)

        for leg_id in all_leg_ids:
            aisle_name_obj = AisleGroup.objects.filter(
                site=site_id, attached_leg_id=leg_id
            ).first()
            name = aisle_name_obj.aisleGroupName if aisle_name_obj else leg_id
            logger.debug("%s %s", "name is", name)
            unitConsumptionList = []
            savingConsumptionList = []

            for i in range(24):
                unit_consumption = 0.0
                energy_saved = 0.0
                hourly_data = hourly_data_map.get((leg_id, i))

                if hourly_data:
                    unit_consumption = hourly_data.unit_consumption
                    energy_saved = hourly_data.energy_saved

                unitConsumptionList.append(round(unit_consumption, 2))
                savingConsumptionList.append(round(energy_saved, 2))

            dataList.append(
                {"name": name, "data": unitConsumptionList, "type": "column"}
            )
            savingList.append(
                {"name": name, "data": savingConsumptionList, "type": "column"}
            )

        if site.is_live:
            latest_baseline = (
                SiteBaseline.objects.filter(associated_site_id=site_id)
                .exclude(Q(baseline_to__isnull=False))
                .aggregate(Sum("baseline_value"))["baseline_value__sum"]
            )

            if datetime.now().date() == date.date() and latest_baseline is not None:
                baseline_list = [round(latest_baseline / 24, 2)] * 24
            else:
                previous_baseline = DailySiteReading.objects.filter(
                    associated_Site=site, reading_for=date.date()
                ).aggregate(Sum("daily_baseline_value"))["daily_baseline_value__sum"]

                baseline_list = (
                    [round(previous_baseline / 24, 2)] * 24
                    if previous_baseline is not None
                    else [0] * 24
                )

            dataList.append(
                {"name": "baseline", "data": baseline_list, "type": "spline"}
            )

        # if site.is_live:
        #    baseline_values = HourlySiteReading.objects.filter(
        #        associated_Site=site, reading_from__date=date, is_visible=True
        #    ).values('reading_from__hour').annotate(baseline_data=Sum('hourly_baseline_value')).order_by('reading_from__hour')

        #   baselineList = [baseline['baseline_data'] for baseline in baseline_values]
        #   dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})

        end_time = datetime.now()
        logger.debug("%s %s", "function end time is:", end_time)
        time_taken = end_time - start_time
        logger.debug("%s %s", "time_taken:", time_taken)

        return Response(
            {"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList}
        )


class DownloadExcel(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data", data)
        site_id = data.get("site_id")
        if int(site_id) == 34:
            site_id = 29
        user_type = int(data.get("user_type", ""))
        logger.debug("%s %s", "user_type", user_type)
        start_date = data.get("from_date")
        fromDate = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = data.get("end_date")
        tillDate = datetime.strptime(end_date, "%Y-%m-%d")
        final_list = []
        first_row = ["Date", "TotalConsumption"]
        if user_type == 1:
            aisles = AisleGroup.objects.filter(site=site_id)
        else:
            if int(data.get("site_id", "")) == 34:
                aisles = AisleGroup.objects.filter(
                    attached_leg_id__in=[259, 276, 260, 261, 710]
                )
            else:
                aisles = AisleGroup.objects.filter(site=site_id, is_visible=True)
        for i in aisles:
            first_row.append(i.aisleGroupName)
        final_list.extend([first_row])
        all_leg_id = [aisle.attached_leg_id for aisle in aisles]
        total_days = tillDate - fromDate
        total_days = total_days.days + 1
        for i in range(total_days):
            date = fromDate + timedelta(days=i)
            unit_consumption_array = [datetime.strftime(date, "%d-%b-%Y"), 0]
            site_consumption = 0
            for aisle in all_leg_id:
                daily = DailySiteReading.objects.filter(
                    associated_Site=site_id, leg_id=aisle, reading_for=date
                )
                if daily.exists():
                    consumption = round(daily[0].unit_consumption, 2)
                else:
                    consumption = 0
                site_consumption += round(consumption, 2)
                unit_consumption_array.append(consumption)
            unit_consumption_array[1] = site_consumption
            final_list.extend([unit_consumption_array])

        df = pd.DataFrame(final_list)
        file_name = "output.csv"
        # Set the return value of the HttpResponse
        response = HttpResponse(
            content_type="text/csv",
        )
        response["filename"] = file_name
        response["Content-Disposition"] = "attachment; filename={}".format(file_name)
        df.to_csv(response, index=False, header=False)
        return response


class EnergySavingMonthlyBarChartbackup(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        t1 = time.time()
        data = request.data
        site_id = data.get("site_id", "")
        if int(site_id) == 34:
            site_id = 29
        try:
            site = Site.objects.get(id=site_id)
            live_date = site.live_date
            previous_date = live_date - timedelta(days=1)
            from_date = data.get("from_date", "")
            till_date = data.get("till_date", "")
            user_type = int(data.get("user_type", ""))
            fromDate = datetime.strptime(from_date, "%Y/%m/%d")
            tillDate = datetime.strptime(till_date, "%Y/%m/%d")
            currentDate = datetime.now()
            dateList = []
            dataList = []
            savingDataList = []
            a = ""
            if tillDate.month == currentDate.month:
                logger.debug("%s", "$$$$$$$$$$$$$$$$$$$")
                a = "tttt"
                if user_type == 1:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(
                            site_id=site_id, is_visible=True
                        )
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_ids,
                    reading_for__range=[
                        tillDate.date() - timedelta(days=29),
                        tillDate.date(),
                    ],
                    is_visible=True,
                )
                logger.debug("%s %s", "all_data", all_data)
                all_dates = [
                    (tillDate - timedelta(days=29 - i)).date() for i in range(30)
                ]
                logger.debug("%s %s", "all dates: ", all_dates)
                output = {}
                for i in all_data:
                    # print("all_data : ",all_data)
                    logger.debug("%s %s", "##: ", i.reading_for)
                    indx = all_dates.index(i.reading_for)
                    aisle_name = i.aisle_group.aisleGroupName
                    if aisle_name in output:
                        if (
                            user_type in [4, 5] and previous_date.date() < i.reading_for
                        ) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption, 2)
                    else:
                        output[aisle_name] = [0 for i in range(30)]
                        if (
                            user_type in [4, 5] and previous_date.date() < i.reading_for
                        ) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption, 2)

                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", "")) == 34:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id, leg_id__in=[259, 260, 261, 276]
                        )
                    else:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id
                        )
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", "")) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site,
                                aisle_group__in=[259, 260, 261, 276],
                            )
                        elif int(data.get("site_id", "")) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=29
                            ).exclude(Q(aisle_group__in=[259, 260, 261, 276]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site
                            )
                        # latest_baseline_value = latest_baseline_value['baseline_value__sum']
                        for i in range(30):
                            date = tillDate - timedelta(days=29 - i)
                            baseline_value = latest_baseline_value.filter(
                                Q(baseline_to__gte=date.date())
                                | Q(
                                    Q(baseline_from__lte=date.date())
                                    & Q(baseline_to__isnull=True)
                                )
                            ).aggregate(Sum("baseline_value"))
                            try:
                                baseline_value = baseline_value["baseline_value__sum"]
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                logger.debug("%s %s", "Exception 1 is", e)
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                    dataList.append(
                        {"name": "baseline", "data": baselineList, "type": "spline"}
                    )
            else:
                logger.debug("%s", "^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^")
                a = "1111"
                total_days = (tillDate - fromDate).days + 1
                logger.debug("%s %s", "total_days", total_days)
                if user_type == 1:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(
                            site_id=site_id, is_visible=True
                        )
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_ids,
                    reading_for__range=[fromDate.date(), tillDate.date()],
                    is_visible=True,
                )
                all_dates = [
                    (tillDate - timedelta(days=(total_days - 1) - i)).date()
                    for i in range(total_days)
                ]
                logger.debug("%s %s", "dates: ", all_dates)
                output = {}
                for i in all_data:
                    logger.debug("%s %s", "@@: ", i.reading_for)
                    indx = all_dates.index(i.reading_for)
                    aisle_name = i.aisle_group.aisleGroupName
                    if aisle_name in output:
                        if (
                            user_type in [4, 5] and previous_date.date() < i.reading_for
                        ) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption, 2)
                    else:
                        output[aisle_name] = [0 for i in range(total_days)]
                        if (
                            user_type in [4, 5] and previous_date.date() < i.reading_for
                        ) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption, 2)

                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", "")) == 34:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id, leg_id__in=[259, 260, 261, 276]
                        )
                    else:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id
                        )
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", "")) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site,
                                aisle_group__in=[259, 260, 261, 276],
                            )
                        elif int(data.get("site_id", "")) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=29
                            ).exclude(Q(aisle_group__in=[259, 260, 261, 276]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site
                            )
                        for i in range(total_days):
                            date = tillDate - timedelta(days=(total_days - 1) - i)
                            baseline_value = latest_baseline_value.filter(
                                Q(baseline_to__gte=date.date())
                                | Q(
                                    Q(baseline_from__lte=date.date())
                                    & Q(baseline_to__isnull=True)
                                )
                            ).aggregate(Sum("baseline_value"))
                            try:
                                baseline_value = baseline_value["baseline_value__sum"]
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                                logger.debug("%s %s", "Exception 2 is", e)
                    dataList.append(
                        {"name": "baseline", "data": baselineList, "type": "spline"}
                    )
            t2 = time.time()
            return Response(
                {
                    "result": 1,
                    "Dates": all_dates,
                    "Data": dataList,
                    "SavingData": savingDataList,
                }
            )
        except Exception as err:
            return Response(
                {"status": 500, "msg": str(err), "dates": all_dates, "a": a}
            )


class EnergySavingMonthlyBarChart(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        t1 = time.time()
        data = request.data
        site_id = data.get("site_id", "")
        if int(site_id) == 34:
            site_id = 29
        try:
            site = Site.objects.get(id=site_id)
            live_date = site.live_date
            previous_date = live_date - timedelta(days=1)
            from_date = data.get("from_date", "")
            till_date = data.get("till_date", "")
            user_type = int(data.get("user_type", ""))
            fromDate = datetime.strptime(from_date, "%Y/%m/%d")
            tillDate = datetime.strptime(till_date, "%Y/%m/%d")
            currentDate = datetime.now()
            dateList = []
            dataList = []
            savingDataList = []
            a = ""
            if tillDate.month == currentDate.month:
                logger.debug("%s", "$$$$$$$$$$$$$$$$$$$")
                a = "tttt"
                if user_type == 1:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(
                            site_id=site_id, is_visible=True
                        )
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_ids,
                    reading_for__range=[
                        tillDate.date() - timedelta(days=29),
                        tillDate.date(),
                    ],
                    is_visible=True,
                )
                logger.debug("%s %s", "all_data", all_data)
                all_dates = [
                    (tillDate - timedelta(days=29 - i)).date() for i in range(30)
                ]
                logger.debug("%s %s", "all dates: ", all_dates)
                output = {}
                for i in all_data:
                    aisle_name = i.aisle_group.aisleGroupName
                    if (
                        user_type in [4, 5] and previous_date.date() < i.reading_for
                    ) or user_type == 1:
                        indx = (
                            all_dates.index(i.reading_for)
                            if i.reading_for in all_dates
                            else None
                        )
                        if aisle_name in output:
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)
                        else:
                            output[aisle_name] = [0 for _ in range(30)]
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)

                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", "")) == 34:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id,
                            leg_id__in=[259, 260, 261, 276, 710],
                        )
                    else:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id
                        )
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", "")) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site,
                                aisle_group__in=[259, 260, 261, 276, 710],
                            )
                        elif int(data.get("site_id", "")) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=29
                            ).exclude(Q(aisle_group__in=[259, 260, 261, 276, 710]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site
                            )
                        # latest_baseline_value = latest_baseline_value['baseline_value__sum']
                        for i in range(30):
                            date = tillDate - timedelta(days=29 - i)
                            baseline_value = latest_baseline_value.filter(
                                Q(baseline_to__gte=date.date())
                                | Q(
                                    Q(baseline_from__lte=date.date())
                                    & Q(baseline_to__isnull=True)
                                )
                            ).aggregate(Sum("baseline_value"))
                            try:
                                baseline_value = baseline_value["baseline_value__sum"]
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                logger.debug("%s %s", "Exception 1 is", e)
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                    dataList.append(
                        {"name": "baseline", "data": baselineList, "type": "spline"}
                    )
            else:
                logger.debug("%s", "^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^")
                a = "1111"
                total_days = (tillDate - fromDate).days + 1
                logger.debug("%s %s", "total_days", total_days)
                if user_type == 1:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", "")) == 34:
                        aisle_group = AisleGroup.objects.filter(
                            attached_leg_id__in=[259, 260, 261, 276, 710]
                        )
                    else:
                        aisle_group = AisleGroup.objects.filter(
                            site_id=site_id, is_visible=True
                        )
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_ids,
                    reading_for__range=[fromDate.date(), tillDate.date()],
                    is_visible=True,
                )
                all_dates = [
                    (tillDate - timedelta(days=(total_days - 1) - i)).date()
                    for i in range(total_days)
                ]
                logger.debug("%s %s", "dates: ", all_dates)
                output = {}
                for i in all_data:
                    aisle_name = i.aisle_group.aisleGroupName
                    if (
                        user_type in [4, 5] and previous_date.date() < i.reading_for
                    ) or user_type == 1:
                        indx = (
                            all_dates.index(i.reading_for)
                            if i.reading_for in all_dates
                            else None
                        )
                        if aisle_name in output:
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)
                        else:
                            output[aisle_name] = [0 for _ in range(30)]
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)

                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", "")) == 34:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id,
                            leg_id__in=[259, 260, 261, 276, 710],
                        )
                    else:
                        baseline = SiteBaseline.objects.filter(
                            associated_site_id=site_id
                        )
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", "")) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site,
                                aisle_group__in=[259, 260, 261, 276, 710],
                            )
                        elif int(data.get("site_id", "")) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=29
                            ).exclude(Q(aisle_group__in=[259, 260, 261, 276, 710]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(
                                associated_site_id=site
                            )
                        for i in range(total_days):
                            date = tillDate - timedelta(days=(total_days - 1) - i)
                            baseline_value = latest_baseline_value.filter(
                                Q(baseline_to__gte=date.date())
                                | Q(
                                    Q(baseline_from__lte=date.date())
                                    & Q(baseline_to__isnull=True)
                                )
                            ).aggregate(Sum("baseline_value"))
                            try:
                                baseline_value = baseline_value["baseline_value__sum"]
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                                logger.debug("%s %s", "Exception 2 is", e)
                    dataList.append(
                        {"name": "baseline", "data": baselineList, "type": "spline"}
                    )
            t2 = time.time()
            return Response(
                {
                    "result": 1,
                    "Dates": all_dates,
                    "Data": dataList,
                    "SavingData": savingDataList,
                }
            )
        except Exception as err:
            return Response(
                {"status": 500, "msg": str(err), "dates": all_dates, "a": a}
            )


class EnergySavingMonthlyBarChart_new(APIView):
    permission_classes = [AllowAny]
    throttle_classes = []

    @entryExit
    def post(self, request):
        data = request.data
        site_id = int(data.get("site_id", 0))

        try:
            site = Site.objects.get(id=site_id)
            from_date = datetime.strptime(data.get("from_date", ""), "%Y/%m/%d")
            till_date = datetime.strptime(data.get("till_date", ""), "%Y/%m/%d")
            user_type = int(data.get("user_type", 0))
            logger.debug("%s %s %s", from_date, till_date, user_type)
            total_days = (till_date - from_date).days + 1

            all_dates = [
                (till_date - timedelta(days=i)).date() for i in range(total_days)
            ]
            all_dates.reverse()
            logger.debug("%s", all_dates)

            # Add is_visible condition only if user_type is not 1 and user_type is not 6
            if user_type in [1, 6]:
                aisle_group = AisleGroup.objects.filter(virtual_siteID=site)
            else:
                aisle_group = AisleGroup.objects.filter(
                    virtual_siteID=site, is_visible=True
                )
            logger.debug("%s", aisle_group)

            aisle_map = {
                aisle.attached_leg_id: aisle.aisleGroupName for aisle in aisle_group
            }
            all_leg_ids = list(aisle_map.keys())

            all_data = DailySiteReading.objects.filter(
                aisle_group__virtual_siteID=site,
                leg_id__in=all_leg_ids,
                reading_for__range=[from_date.date(), till_date.date()],
                is_visible=True,
            ).values("leg_id", "reading_for", "unit_consumption")
            logger.debug("%s", all_data)

            data_dict = {}
            for record in all_data:
                leg_id, reading_for, unit_consumption = record.values()
                aisle_name = aisle_map.get(leg_id, "Unknown")
                idx = all_dates.index(reading_for) if reading_for in all_dates else None
                if idx is not None:
                    data_dict.setdefault(aisle_name, [0] * total_days)[idx] = round(
                        unit_consumption, 2
                    )

            data_list = [
                {"name": k, "data": v, "type": "column"} for k, v in data_dict.items()
            ]

            # Build aisle_name -> list of leg_ids mapping for per-aisle baseline lookup
            aisle_leg_map = {}
            for leg_id, aisle_name in aisle_map.items():
                aisle_leg_map.setdefault(aisle_name, []).append(leg_id)

            saving_data_list = []
            baseline_list = []
            if site.is_live:
                latest_baseline_values = SiteBaseline.objects.filter(
                    leg_id__in=all_leg_ids
                )
                logger.debug("%s", latest_baseline_values)

                # Total baseline list (sum of all aisles per date)
                for date in all_dates:
                    baseline_value = (
                        latest_baseline_values.filter(baseline_from__lte=date)
                        .filter(Q(baseline_to__gte=date) | Q(baseline_to__isnull=True))
                        .aggregate(Sum("baseline_value"))["baseline_value__sum"]
                        or 0
                    )
                    baseline_list.append(round(baseline_value, 2))

                data_list.append(
                    {"name": "baseline", "data": baseline_list, "type": "spline"}
                )

                # Compute per-aisle savings without altering unit consumption Data array
                for aisle_name, consumption_values in data_dict.items():
                    leg_ids_for_aisle = aisle_leg_map.get(aisle_name, [])
                    aisle_savings = []
                    for idx, date in enumerate(all_dates):
                        aisle_baseline = (
                            latest_baseline_values.filter(
                                leg_id__in=leg_ids_for_aisle, baseline_from__lte=date
                            )
                            .filter(
                                Q(baseline_to__gte=date) | Q(baseline_to__isnull=True)
                            )
                            .aggregate(Sum("baseline_value"))["baseline_value__sum"]
                            or 0
                        )
                        saving = round(aisle_baseline - consumption_values[idx], 2)
                        aisle_savings.append(max(saving, 0.0))
                    saving_data_list.append(
                        {"name": aisle_name, "data": aisle_savings, "type": "column"}
                    )
            else:
                saving_data_list = []

            return Response(
                {
                    "result": 1,
                    "Dates": all_dates,
                    "Data": data_list,
                    "SavingData": saving_data_list,
                }
            )

        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class DownloadExcel_new(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = int(data.get("site_id"))
            site_id = 29 if site_id == 34 else site_id
            user_type = int(data.get("user_type", ""))

            start_date = datetime.strptime(data.get("from_date"), "%Y-%m-%d")
            end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")

            # Fetch aisles more efficiently
            if user_type == 1:
                aisles = AisleGroup.objects.filter(site=site_id)
            else:
                if int(data.get("site_id")) == 34:
                    aisles = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 710, 276]
                    )
                else:
                    aisles = AisleGroup.objects.filter(site=site_id, is_visible=True)

            aisle_names = [aisle.aisleGroupName for aisle in aisles]
            leg_ids = [aisle.attached_leg_id for aisle in aisles]

            # Fetch all relevant readings in one query
            readings = (
                DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    is_visible=True,
                    leg_id__in=leg_ids,
                    reading_for__range=[start_date, end_date],
                )
                .values("leg_id", "reading_for")
                .annotate(total_consumption=Sum("unit_consumption"))
            )

            # Organize readings by date and leg_id
            readings_dict = defaultdict(lambda: defaultdict(float))
            for reading in readings:
                date = reading["reading_for"].strftime("%d-%b-%Y")
                readings_dict[date][reading["leg_id"]] = round(
                    reading["total_consumption"], 2
                )

            # Prepare data for DataFrame
            header = ["Date", "TotalConsumption"] + aisle_names
            data_rows = []

            for i in range((end_date - start_date).days + 1):
                current_date = (start_date + timedelta(days=i)).strftime("%d-%b-%Y")
                daily_readings = readings_dict.get(current_date, {})
                row = [current_date]
                total = 0
                for leg_id in leg_ids:
                    consumption = daily_readings.get(leg_id, 0)
                    total += consumption
                    row.append(consumption)
                row.insert(1, total)
                data_rows.append(row)

            # Create CSV from DataFrame
            df = pd.DataFrame(data_rows, columns=header)
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f"attachment; filename=output.csv"
            df.to_csv(response, index=False)

            return response

        except Exception as e:
            return Response({"message": str(e)})


class EnergySavingMonthlyBarChartTestVB(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        site_id = int(data.get("site_id", 0))

        try:
            site = Site.objects.get(id=site_id)
            from_date = datetime.strptime(data.get("from_date", ""), "%Y/%m/%d")
            till_date = datetime.strptime(data.get("till_date", ""), "%Y/%m/%d")
            user_type = int(data.get("user_type", 0))
            logger.debug("%s %s %s", from_date, till_date, user_type)
            total_days = (till_date - from_date).days + 1

            all_dates = [
                (till_date - timedelta(days=i)).date() for i in range(total_days)
            ]
            all_dates.reverse()
            logger.debug("%s", all_dates)

            # Add is_visible condition only if user_type is not 1 and the site is not 34
            is_visible = False if user_type == 1 else True
            if user_type == 1:
                aisle_group = AisleGroup.objects.filter(virtual_siteID=site)
            else:
                aisle_group = AisleGroup.objects.filter(
                    virtual_siteID=site, is_visible=True
                )
            logger.debug("%s", aisle_group)
            aisle_map = {
                aisle.attached_leg_id: aisle.aisleGroupName for aisle in aisle_group
            }
            all_leg_ids = list(aisle_map.keys())

            all_data = DailySiteReading.objects.filter(
                aisle_group__virtual_siteID=site,
                leg_id__in=all_leg_ids,
                reading_for__range=[from_date.date(), till_date.date()],
                is_visible=True,
            ).values("leg_id", "reading_for", "unit_consumption")
            logger.debug("%s", all_data)

            data_dict = {}
            for record in all_data:
                leg_id, reading_for, unit_consumption = record.values()
                aisle_name = aisle_map.get(leg_id, "Unknown")
                idx = all_dates.index(reading_for) if reading_for in all_dates else None
                if idx is not None:
                    data_dict.setdefault(aisle_name, [0] * total_days)[idx] = round(
                        unit_consumption, 2
                    )

            data_list = [
                {"name": k, "data": v, "type": "column"} for k, v in data_dict.items()
            ]
            saving_data_list = data_list.copy()

            baseline_list = []
            if site.is_live:
                baseline_filter = Q(associated_site_id=site_id, leg_id__in=all_leg_ids)
                latest_baseline_values = SiteBaseline.objects.filter(
                    leg_id__in=all_leg_ids
                )
                logger.debug("%s", latest_baseline_values)

                for date in all_dates:
                    baseline_value = (
                        latest_baseline_values.filter(baseline_from__lte=date)
                        .filter(Q(baseline_to__gte=date) | Q(baseline_to__isnull=True))
                        .aggregate(Sum("baseline_value"))["baseline_value__sum"]
                        or 0
                    )
                    baseline_list.append(round(baseline_value, 2))

                data_list.append(
                    {"name": "baseline", "data": baseline_list, "type": "spline"}
                )

            return Response(
                {
                    "result": 1,
                    "Dates": all_dates,
                    "Data": data_list,
                    "SavingData": saving_data_list,
                }
            )

        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class EnergySavingsHourlyExcelDownloadVB(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def get(self, request):
        import re
        from datetime import date

        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        user_type = getattr(request.user, "UserType", None)
        if user_type not in [1, 2]:
            return Response(
                {"result": 0, "msg": "Access denied: admin only"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            # Combine parameters from both query parameters and request body
            data = {}
            if hasattr(request, "query_params") and request.query_params:
                try:
                    data.update(request.query_params.dict())
                except AttributeError:
                    data.update(request.query_params)
            if hasattr(request, "data") and request.data:
                try:
                    data.update(request.data.dict())
                except AttributeError:
                    try:
                        data.update(request.data)
                    except (TypeError, ValueError):
                        pass

            site_id = data.get("site_id")
            if not site_id:
                return Response(
                    {"result": 0, "msg": "site_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                site_id = int(site_id)
            except ValueError:
                return Response(
                    {"result": 0, "msg": "site_id must be an integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                site = Site.objects.only("site_name", "is_live", "site_type").get(
                    id=site_id
                )
            except Site.DoesNotExist:
                return Response(
                    {"result": 0, "msg": "Site not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Check permissions based on user_type and site_type
            if site.site_type == 2:
                if user_type not in [1, 2]:
                    return Response(
                        {"result": 0, "msg": "Access denied: admin only"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            elif site.site_type in [1, 3, 4, 5]:
                if user_type != 1:
                    return Response(
                        {
                            "result": 0,
                            "msg": "Access denied: this feature is restricted to Super Admin",
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                return Response(
                    {"result": 0, "msg": "Invalid or unsupported site type"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from_date_str = (
                data.get("from_date") or data.get("from") or data.get("date") or ""
            ).strip()
            end_date_str = (
                data.get("end_date")
                or data.get("to_date")
                or data.get("to")
                or data.get("till_date")
                or ""
            ).strip()

            if not from_date_str:
                return Response(
                    {
                        "result": 0,
                        "msg": "Date parameter is required (from_date/from/date)",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not end_date_str:
                end_date_str = from_date_str

            def parse_date(d_str):
                for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d-%b-%Y"):
                    try:
                        return datetime.strptime(d_str, fmt)
                    except ValueError:
                        pass
                raise ValueError(
                    f"Time data '{d_str}' does not match format '%Y/%m/%d', '%Y-%m-%d', or '%d-%b-%Y'"
                )

            try:
                from_date = parse_date(from_date_str)
                end_date = parse_date(end_date_str)
            except ValueError as e:
                return Response(
                    {"result": 0, "msg": str(e)}, status=status.HTTP_400_BAD_REQUEST
                )

            if from_date > end_date:
                return Response(
                    {"result": 0, "msg": "from_date cannot be after end_date"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if (end_date - from_date).days > 31:
                return Response(
                    {"result": 0, "msg": "Date range cannot exceed 31 days"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            target_date_from = from_date.date()
            target_date_to = end_date.date()

            # Determine aisle groups associated strictly to site_id considering virtual_siteID concept
            if site_id == 34:
                aisle_group_qs = AisleGroup.objects.filter(
                    attached_leg_id__in=["259", "260", "261", "276", "710"]
                )
            else:
                virtual_aisles = AisleGroup.objects.filter(virtual_siteID_id=site_id)
                if virtual_aisles.exists():
                    aisle_group_qs = virtual_aisles
                else:
                    aisle_group_qs = AisleGroup.objects.filter(site_id=site_id)

            if user_type not in [1, 2, 6] and site_id != 34:
                aisle_group_qs = aisle_group_qs.filter(is_visible=True)

            aisle_map = dict(
                aisle_group_qs.exclude(attached_leg_id__isnull=True).values_list(
                    "attached_leg_id", "aisleGroupName"
                )
            )
            aisle_map = {str(k): v for k, v in aisle_map.items()}

            if not aisle_map:
                return Response(
                    {"result": 0, "msg": "No aisle data found for the selected site"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            str_leg_ids = list(aisle_map.keys())

            # Sort leg IDs to guarantee stable column ordering
            sorted_leg_ids = sorted(
                str_leg_ids, key=lambda x: aisle_map.get(str(x), str(x))
            )
            aisle_names = [
                aisle_map.get(str(leg_id), str(leg_id)) for leg_id in sorted_leg_ids
            ]

            # Fetch HourlySiteReading in bulk for only the associated aisle leg IDs
            start_of_range = datetime.combine(target_date_from, datetime.min.time())
            end_of_range_exclusive = datetime.combine(
                target_date_to + timedelta(days=1), datetime.min.time()
            )

            range_data = (
                HourlySiteReading.objects.filter(
                    leg_id__in=str_leg_ids,
                    reading_from__gte=start_of_range,
                    reading_from__lt=end_of_range_exclusive,
                    is_visible=True,
                )
                .filter(
                    Q(associated_Site_id=site_id)
                    | Q(aisle_group__virtual_siteID_id=site_id)
                    | Q(aisle_group__site_id=site_id)
                )
                .values("leg_id", "reading_from", "unit_consumption", "energy_saved")
            )

            # Map hourly data by (date, leg_id, hour)
            hourly_data_map = {}
            for item in range_data:
                r_datetime = item["reading_from"]
                if not r_datetime:
                    continue
                r_date = r_datetime.date()
                r_hour = r_datetime.hour
                hourly_data_map[(r_date, str(item["leg_id"]), r_hour)] = item

            # Fetch baselines for each date in the range in-memory to prevent multiple DB queries or reliance on corrupt DailySiteReading values
            baselines = []
            if site.is_live:
                baselines = list(
                    SiteBaseline.objects.filter(
                        associated_site_id=site_id, leg_id__in=str_leg_ids
                    )
                )

            # Helper to calculate daily baseline value for any date in the range
            def get_daily_baseline_for_date(d):
                if not site.is_live:
                    return 0.0
                total_val = 0.0
                for b in baselines:
                    from_ok = b.baseline_from is None or b.baseline_from <= d
                    to_ok = b.baseline_to is None or b.baseline_to >= d
                    if from_ok and to_ok:
                        total_val += b.baseline_value or 0.0
                return total_val

            # Generate dates in the range
            total_days = (target_date_to - target_date_from).days + 1
            date_list = [
                target_date_from + timedelta(days=i) for i in range(total_days)
            ]

            # Data structures for Excel
            hourly_rows = []

            for d in date_list:
                # Baseline for the day
                day_total_baseline = get_daily_baseline_for_date(d)

                # Daily accumulation variables
                day_hourly_rows = []

                for h in range(24):
                    hour_str = "{:02d}:00".format(h)
                    baseline_value = (
                        round(day_total_baseline / 24.0, 2)
                        if day_total_baseline
                        else 0.0
                    )

                    aisle_values = []
                    for leg_id in sorted_leg_ids:
                        hourly_data = hourly_data_map.get((d, str(leg_id), h))
                        if hourly_data:
                            val = hourly_data["unit_consumption"] or 0.0
                        else:
                            val = 0.0
                        aisle_values.append(round(val, 2))

                    total_consumption = round(sum(aisle_values), 2)
                    if site.is_live:
                        savings = round(baseline_value - total_consumption, 2)
                    else:
                        savings = 0.0

                    day_hourly_rows.append(
                        [d, hour_str, baseline_value, savings, total_consumption]
                        + aisle_values
                    )

                hourly_rows.extend(day_hourly_rows)

            # Build DataFrames
            hourly_headers = [
                "Date",
                "Hour",
                "Baseline (KWH)",
                "Savings (KWH)",
                "Total Consumption (KWH)",
            ] + aisle_names
            df_hourly = pd.DataFrame(hourly_rows, columns=hourly_headers)

            # Create Excel workbook in-memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_hourly.to_excel(writer, sheet_name="Hourly Readings", index=False)

                workbook = writer.book

                header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                header_fill = PatternFill(
                    start_color="2C3E50", end_color="2C3E50", fill_type="solid"
                )
                regular_font = Font(name="Calibri", size=11, bold=False)

                thin_side = Side(border_style="thin", color="D3D3D3")
                border = Border(
                    left=thin_side, right=thin_side, top=thin_side, bottom=thin_side
                )

                alignment_center = Alignment(horizontal="center", vertical="center")
                alignment_left = Alignment(horizontal="left", vertical="center")
                alignment_right = Alignment(horizontal="right", vertical="center")

                for sheet_name in ["Hourly Readings"]:
                    worksheet = workbook[sheet_name]
                    worksheet.sheet_view.showGridLines = True

                    # Style headers
                    for col_num in range(1, worksheet.max_column + 1):
                        cell = worksheet.cell(row=1, column=col_num)
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = alignment_center
                        cell.border = border

                    # Style body rows
                    for row_num in range(2, worksheet.max_row + 1):
                        for col_num in range(1, worksheet.max_column + 1):
                            cell = worksheet.cell(row=row_num, column=col_num)
                            cell.font = regular_font
                            cell.border = border

                            val = cell.value
                            if col_num == 1:
                                cell.number_format = "yyyy-mm-dd"
                                cell.alignment = alignment_center
                            elif sheet_name == "Hourly Readings" and col_num == 2:
                                cell.alignment = alignment_center
                            else:
                                if isinstance(val, (int, float)):
                                    cell.number_format = "#,##0.00"
                                cell.alignment = alignment_right

                    # Autofit column widths
                    for col in worksheet.columns:
                        if not col:
                            continue
                        max_len = 0
                        col_letter = get_column_letter(col[0].column)
                        for cell in col:
                            if cell.value is not None:
                                if isinstance(cell.value, (datetime, date)):
                                    val_str = cell.value.strftime("%Y-%m-%d")
                                else:
                                    val_str = str(cell.value)
                                if len(val_str) > max_len:
                                    max_len = len(val_str)
                        worksheet.column_dimensions[col_letter].width = max(
                            max_len + 3, 12
                        )

            output.seek(0)
            site_name_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", site.site_name)
            file_name = f"{site_name_clean}_hourly_energy_{target_date_from.strftime('%Y-%m-%d')}_to_{target_date_to.strftime('%Y-%m-%d')}.xlsx"

            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="{file_name}"'
            return response

        except Exception as err:
            return Response(
                {"result": 0, "msg": str(err)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        return self.get(request)


class EnergySavingsHourlyBarChartVB(APIView):
    """
    This API is used to get the hourly energy consumption data for a site on a given date. (For Savings Only)
    """

    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        logger.debug("%s %s", "function start time is:", start_time)

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"result": 0, "msg": "Site not found"}, status=404)

        date_str = data.get("date", "")
        try:
            date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response({"result": 0, "msg": "Invalid date format"}, status=400)

        hourList = ["{:02d}:00".format(i) for i in range(24)]
        dataList = []
        savingList = []

        from datetime import timedelta

        # Use exact date for reading_for
        target_date = date.date()

        all_leg_ids = list(
            DailySiteReading.objects.filter(
                aisle_group__virtual_siteID_id=site_id, reading_for=target_date
            )
            .values_list("leg_id", flat=True)
            .distinct()
        )

        start_of_day = date
        end_of_day = start_of_day + timedelta(days=1)

        # Optimize HourlySiteReading query with __gte and __lt instead of __date
        # and remove select_related('aisle_group') to avoid slow joins
        oneDayData = HourlySiteReading.objects.filter(
            aisle_group__virtual_siteID_id=site_id,
            reading_from__gte=start_of_day,
            reading_from__lt=end_of_day,
            is_visible=True,
        ).values("leg_id", "reading_from", "unit_consumption", "energy_saved")

        # Group by leg_id and hour to reduce the number of iterations
        hourly_data_map = {
            (item["leg_id"], item["reading_from"].hour): item for item in oneDayData
        }

        # Fetch AisleGroup names in a single query to eliminate N+1 issue
        aisle_map = dict(
            AisleGroup.objects.filter(
                virtual_siteID_id=site_id, attached_leg_id__in=all_leg_ids
            ).values_list("attached_leg_id", "aisleGroupName")
        )

        for leg_id in all_leg_ids:
            name = aisle_map.get(leg_id, str(leg_id))

            unitConsumptionList = []
            savingConsumptionList = []

            for i in range(24):
                hourly_data = hourly_data_map.get((leg_id, i))

                if hourly_data:
                    unit_consumption = hourly_data["unit_consumption"] or 0.0
                    energy_saved = hourly_data["energy_saved"] or 0.0
                else:
                    unit_consumption = 0.0
                    energy_saved = 0.0

                unitConsumptionList.append(round(unit_consumption, 2))
                savingConsumptionList.append(round(energy_saved, 2))

            dataList.append(
                {"name": name, "data": unitConsumptionList, "type": "column"}
            )
            savingList.append(
                {"name": name, "data": savingConsumptionList, "type": "column"}
            )

        if site.is_live:
            latest_baseline = (
                SiteBaseline.objects.filter(aisle_group__virtual_siteID_id=site_id)
                .exclude(Q(baseline_to__isnull=False))
                .aggregate(Sum("baseline_value"))["baseline_value__sum"]
            )

            if datetime.now().date() == target_date and latest_baseline is not None:
                baseline_list = [round(latest_baseline / 24, 2)] * 24
            else:
                previous_baseline = DailySiteReading.objects.filter(
                    aisle_group__virtual_siteID_id=site_id, reading_for=target_date
                ).aggregate(Sum("daily_baseline_value"))["daily_baseline_value__sum"]

                baseline_list = (
                    [round(previous_baseline / 24, 2)] * 24
                    if previous_baseline is not None
                    else [0] * 24
                )

            dataList.append(
                {"name": "baseline", "data": baseline_list, "type": "spline"}
            )

        end_time = datetime.now()
        logger.debug("%s %s", "function end time is:", end_time)
        time_taken = end_time - start_time
        logger.debug("%s %s", "time_taken:", time_taken)

        return Response(
            {"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList}
        )


class DownloadExcelVB(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = int(data.get("site_id"))
            user_type = int(data.get("user_type", ""))

            start_date = datetime.strptime(data.get("from_date"), "%Y-%m-%d")
            end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")

            if user_type == 1:
                aisles = AisleGroup.objects.filter(virtual_siteID_id=site_id)
            else:
                aisles = AisleGroup.objects.filter(
                    virtual_siteID_id=site_id, is_visible=True
                )

            aisle_map = {
                aisle.attached_leg_id: aisle.aisleGroupName for aisle in aisles
            }
            leg_ids = list(aisle_map.keys())

            readings = DailySiteReading.objects.filter(
                aisle_group__virtual_siteID_id=site_id,
                leg_id__in=leg_ids,
                reading_for__range=[start_date.date(), end_date.date()],
                is_visible=True,
            ).values("leg_id", "reading_for", "unit_consumption")

            total_days = (end_date - start_date).days + 1
            all_dates = [
                (start_date + timedelta(days=i)).date() for i in range(total_days)
            ]

            data_dict = {}

            for reading in readings:
                leg_id = reading["leg_id"]
                reading_for = reading["reading_for"]
                unit_consumption = reading["unit_consumption"]

                aisle_name = aisle_map.get(leg_id, "Unknown")

                if reading_for in all_dates:
                    idx = all_dates.index(reading_for)
                    data_dict.setdefault(aisle_name, [0] * total_days)[idx] = round(
                        unit_consumption, 2
                    )

            latest_baseline_values = SiteBaseline.objects.filter(leg_id__in=leg_ids)

            aisle_names = list(data_dict.keys())

            header = [
                "Date",
                "Baseline",
                "Savings",
                "TotalConsumption (KWH)",
            ] + aisle_names

            data_rows = []

            for idx, current_date in enumerate(all_dates):
                baseline_value = (
                    latest_baseline_values.filter(baseline_from__lte=current_date)
                    .filter(
                        Q(baseline_to__gte=current_date) | Q(baseline_to__isnull=True)
                    )
                    .aggregate(Sum("baseline_value"))["baseline_value__sum"]
                    or 0
                )

                row = [current_date.strftime("%d-%b-%Y")]
                total = 0

                for aisle_name in aisle_names:
                    consumption = data_dict[aisle_name][idx]
                    total += consumption
                    row.append(consumption)

                row.insert(1, round(total, 2))
                row.insert(1, round(baseline_value - total, 2))
                row.insert(1, round(baseline_value, 2))

                data_rows.append(row)

            df = pd.DataFrame(data_rows, columns=header)

            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = "attachment; filename=output.csv"
            df.to_csv(response, index=False)

            return response

        except Exception as e:
            return Response({"message": str(e)})


class ParticularSiteSnapshotEnergySavingApiVB(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        # print("data of site snapshot", data)
        site_id = data.get("site_id", "")
        # print("site id is: ", site_id)
        site = Site.objects.get(id=site_id)
        carbon_visible = False
        carbon_emission_value = 0
        if site.is_carbon_emission_visible:
            carbon_emission_value = site.carbon_emission_value
            carbon_visible = True
        live_date = site.live_date
        # print("live_date :",live_date)
        user_type = data.get("user_type")
        # print("site data", site)
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        previous = datetime.strftime(previous_date, "%d-%b-%Y")
        if int(data.get("site_id", "")) == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023)
        else:
            baseline_date = site.baseline_date.date()
        date = datetime.strftime(baseline_date, "%d-%b-%Y")
        alarm = AlarmNotifications.objects.filter(site_id=site, user_level=4).count()
        # print("alarm count on site page: ", alarm)
        # daily = DailySiteReading.objects.filter(associated_Site=site)
        if site.live_date:
            # print("inside live date if condition: ")
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        virtual_siteID=site_id, is_visible=True
                    )
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    aisle_group__virtual_siteID=site,
                    leg_id__in=all_leg_id,
                    reading_for__gte=baseline_date,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )

            else:
                if int(data.get("site_id", "")) == 34:
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
                    leg_id__in=all_leg_id,
                    reading_for__gte=baseline_date,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )
                live_date = site.live_date
                live_date = datetime.strftime(live_date, "%Y/%m/%d")

        else:
            # print("inside else condition. site is not live")
            if user_type == 1:
                if int(data.get("site_id", "")) == 34:
                    aisle_group = AisleGroup.objects.filter(
                        attached_leg_id__in=[259, 260, 261, 276, 710]
                    )
                else:
                    aisle_group = AisleGroup.objects.filter(
                        virtual_siteID=site_id, is_visible=True
                    )
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    aisle_group__virtual_siteID=site,
                    reading_for__gte=baseline_date,
                    leg_id__in=all_leg_id,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )
            else:
                if int(data.get("site_id", "")) == 34:
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
                    reading_for__lte=previous_date,
                    reading_for__gte=baseline_date,
                    leg_id__in=all_leg_id,
                )
                live_date = "Not Live yet"
        energyConsumed = 0.0
        energySaved = 0.0
        carbon_saved = 0.0

        for i in daily:
            # print("inside for loop!!!!")
            energyConsumed += i.unit_consumption
            # if i.energy_saved >= 0:
            energySaved += i.daily_baseline_value
        energySaved = energySaved - energyConsumed
        if carbon_visible:
            carbon_saved = energySaved * carbon_emission_value
        try:
            percentageSaved = (
                str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
            )
            # live_date = site.live_date
            # live_date = datetime.strftime(live_date, "%Y/%m/%d")
        except Exception as e:
            logger.debug("%s %s", "exception is", e)
            percentageSaved = str(0.0) + " %"
        return Response(
            {
                "result": 1,
                "alarms": alarm,
                "energy_consumed": str(round(energyConsumed, 1)),
                "saved_energy": str(round(energySaved, 1)),
                "carbon_emission_saved": str(round(carbon_saved, 1)),
                "percentage_saved": percentageSaved,
                "live_date": date,
                "previous_date": previous,
                "site_live_date": live_date,
            }
        )
