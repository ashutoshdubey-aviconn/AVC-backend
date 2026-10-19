"""Baseline history and baseline/saving data."""

from datetime import datetime, timedelta

from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AisleGroup, DailySiteReading, Site, SiteBaseline
from wareApp.utility import entryExit, logger


class BaselineHistory(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "baseline history data", data)
        site_id = data.get("site_id", "")
        dataList = []
        dateList = []
        all_leg_id = SiteBaseline.objects.distinct("leg_id").filter(
            associated_site_id=site_id
        )
        logger.debug("%s", "hii")
        for i in all_leg_id:
            leg_id = i.leg_id
            data = []
            for j in SiteBaseline.objects.filter(
                associated_site_id=site_id, leg_id=leg_id
            ).order_by("baseline_from"):
                baseline_value = j.baseline_value
                baseline_from = j.baseline_from
                baseline_from = datetime.strftime(baseline_from, "%Y/%m/%d")
                dateList.append(baseline_from)
                data.append(round(baseline_value, 2))
            aisle_name = AisleGroup.objects.filter(site=site_id, attached_leg_id=leg_id)
            if aisle_name.exists():
                name = aisle_name[0].aisleGroupName
            else:
                name = leg_id
            dataList.append({"name": name, "data": data})
        logger.debug("%s %s", "dataList", dataList)
        logger.debug("%s %s", "dateList", list(set(dateList)))
        return Response({"result": 1, "Data": dataList, "Dates": dateList})


class BaselineData(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data", data)
        site_id = data.get("site_id", "")
        date = data.get("date", "")
        date = datetime.strptime(date, "%Y/%m/%d")
        DataList = []
        logger.debug("%s", "above all leg")
        all_leg = AisleGroup.objects.distinct("aisleGroupName").filter(site_id=site_id)
        logger.debug("%s %s", "all leg data :", all_leg)
        for i in all_leg:
            logger.debug("%s %s", "leg is", i)
            aisle_info = AisleGroup.objects.filter(
                site_id=int(site_id), aisleGroupName=i.aisleGroupName
            )[0]
            logger.debug("%s %s", "aisle info: ", aisle_info)
            current_consumption = DailySiteReading.objects.filter(
                associated_Site=site_id, leg_id=i.attached_leg_id, reading_for=date
            )
            logger.debug("%s %s", "current consumption data: ", current_consumption)
            consumption = 0.0
            if current_consumption.exists():
                consumption += current_consumption[0].unit_consumption
            logger.debug("%s %s", "consumption", consumption)
            data = {
                "aisle_name": aisle_info.aisleGroupName,
                "total_lights": aisle_info.total_lights,
                "expected_consumption": aisle_info.expected_consumption,
                "current_consumption": round(consumption, 2),
            }
            DataList.append(data)
        return Response({"result": 1, "data": DataList})


class SavingBaselineData(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data of saving baseline", data)
        site_id = data.get("siteId", "")
        leg_id = data.get("legId", "")
        baseline_value = data.get("baselineValue", "")
        date = data.get("date", "")
        date = datetime.strptime(date, "%Y/%m/%d")
        site = Site.objects.get(id=site_id)
        logger.debug("%s %s", "site instance", site)
        aisle = AisleGroup.objects.filter(site_id=int(site_id), aisleGroupName=leg_id)[
            0
        ]
        logger.debug("%s %s", "aisle group is:", aisle)
        baseline_data = SiteBaseline.objects.filter(
            associated_site_id=site_id, aisle_group=aisle
        )
        logger.debug("%s %s", "baseline data", baseline_data)
        if baseline_data.exists():
            change_date = date - timedelta(days=1)
            update_field = SiteBaseline.objects.filter(
                associated_site_id=site, aisle_group=aisle
            ).order_by("-baseline_from")[0]
            logger.debug("%s %s", "$$$$$, ", update_field.baseline_from)
            logger.debug("%s %s", "date", date)
            logger.debug("%s %s", "######", update_field)
            if update_field.baseline_from == date.date():
                logger.debug("%s", "inside if ")
                update_field.baseline_value = baseline_value
                logger.debug("%s %s", "@@@@@@@ ", update_field)
                update_field.save()
            else:
                logger.debug("%s", "inside else")
                update_field.baseline_to = change_date
                update_field.save()
                logger.debug("%s %s", "updated field :", update_field)
                baseline = SiteBaseline.objects.create(
                    associated_site_id=site,
                    aisle_group=aisle,
                    leg_id=baseline_data[0].leg_id,
                    baseline_value=baseline_value,
                    baseline_from=date.date(),
                )
                logger.debug("%s %s", "baseline value created :", baseline)
            current_consumption = DailySiteReading.objects.filter(
                associated_Site=site_id,
                leg_id=baseline_data[0].leg_id,
                reading_for=date.date(),
            ).update(daily_baseline_value=baseline_value)

            logger.debug(
                "%s %s", "daily table unit consumption updated", current_consumption
            )
            aisle_group = (
                AisleGroup.objects.distinct("aisleGroupName")
                .filter(site_id=site_id)
                .exclude(aisleGroupName=leg_id)
            )
            logger.debug("%s %s", "all aisle groups", aisle_group)
            for i in aisle_group:
                b = SiteBaseline.objects.filter(
                    associated_site_id=site, leg_id=i.id
                ).order_by("-baseline_from")[0]
                if b.baseline_from != date.date():
                    previous_baseline_value = b.baseline_value
                    b.baseline_to = change_date
                    b.save()
                    new_entry = SiteBaseline.objects.create(
                        associated_site_id=site,
                        leg_id=i.id,
                        aisle_group=i,
                        baseline_value=previous_baseline_value,
                        baseline_from=date,
                    )
                    logger.debug("%s %s", "new entry is", new_entry)
                else:
                    pass
        else:
            logger.debug("%s", "baseline going to saved")
            baseline = SiteBaseline.objects.create(
                associated_site_id=site,
                aisle_group=aisle,
                leg_id=aisle.id,
                baseline_value=baseline_value,
                baseline_from=date,
            )
            logger.debug("%s %s", "baseline value created :", baseline)
            current_consumption = DailySiteReading.objects.filter(
                associated_Site=site_id,
                leg_id=baseline_data[0].leg_id,
                reading_for=date,
            ).update(daily_baseline_value=baseline_value)
            # current_consumption.unit_consumption = baseline_value
            # current_consumption.save()
            logger.debug(
                "%s %s", "daily table unit consumption updated", current_consumption
            )
        return Response({"result": 1, "msg": "baseline value set"})


class AisleLevelBaseline(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        site = Site.objects.get(id=site_id)
        from_date = data.get("from_date", "")
        till_date = data.get("till_date", "")
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        currentDate = datetime.now()
        dateList = []
        dataList = []
        if tillDate.month == currentDate.month:
            all_leg_id = DailySiteReading.objects.distinct("leg_id").filter(
                associated_Site=site
            )
            for leg in all_leg_id:
                baseline = []
                dateList = []
                for i in range(30):
                    date = currentDate - timedelta(days=29 - i)
                    dateList.append(date.date())
                    daily = DailySiteReading.objects.filter(
                        associated_Site=site, leg_id=leg, reading_for=date
                    )
                    baseline_value = 0.0
                    if daily.exists():
                        for j in daily:
                            baseline_value += j.baseline_value
                    baseline.append(baseline_value)
                dataList.append(
                    {"name": leg.leg_id, "data": baseline, "type": "column"}
                )
        else:
            total_days = (tillDate.day - fromDate.day) + 1
            all_leg_id = DailySiteReading.objects.distinct("leg_id").filter(
                associated_Site=site
            )
            for leg in all_leg_id:
                baseline = []
                dateList = []
                for i in range(0, total_days):
                    date = currentDate - timedelta(days=i)
                    dateList.append(date.date())
                    daily = DailySiteReading.objects.filter(
                        associated_Site=site, leg_id=leg, reading_for=date
                    )
                    baseline_value = 0.0
                    if daily.exists():
                        for j in daily:
                            baseline_value += j.baseline_value
                    baseline.append(baseline_value)
                dataList.append(
                    {"name": leg.leg_id, "data": baseline, "type": "column"}
                )
        return Response({"result": 1, "Dates": dateList, "Data": dataList})
