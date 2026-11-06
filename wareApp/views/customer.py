"""Customer-level pages: sites, totals, snapshots and alarm counts."""

from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Count, Q
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    AlarmNotifications,
    CustomerInfo,
    CustomerSiteManager,
    DailySiteReading,
    HourlySiteReading,
    Site,
    User,
)
from rest_framework.authtoken.models import Token

from wareApp.serializers import CustomerInfoSerializer, SiteSerializer
from wareApp.utility import entryExit, logger


class CustomerView(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request, *args):
        customer = CustomerInfo.objects.all()
        logger.debug(customer)
        customer_serializer = CustomerInfoSerializer(customer, many=True)
        logger.debug(customer)
        return Response({"data": customer_serializer.data})


class CustomerTotalConsumption(APIView):
    @entryExit
    def post(self, request, *args):
        data = request.data
        logger.debug("%s %s", "data", data)
        customer_id = data["id"]
        logger.debug(
            "%s %s %s %s", "customer id", customer_id, "id type", type(int(customer_id))
        )
        # customer_id = 2
        customerAllSites = Site.objects.filter(Customer=customer_id).order_by(
            "id"
        )  # no of sites for that customer
        logger.debug("%s", customerAllSites)
        alarm = 0
        current_date = datetime.now()
        start_date = "18 August 2019"  # hardcoded date, should be replaced
        start_date = datetime.strptime(start_date, "%d %B %Y")
        logger.debug("%s", start_date)
        date = abs(current_date.day - start_date.day)
        logger.debug("%s", date)
        baseline_reading = 80  # hardcoded for the time been to be replaced when actual baseline is available
        # earlier_consumption_per_day = baseline_reading/30
        # total_readings = earlier_consumption_per_day * date
        total_readings = baseline_reading * date
        logger.debug("%s", total_readings)
        total_consumption = 0.0
        for i in customerAllSites:
            hourlySiteReading = HourlySiteReading.objects.filter(
                associated_site_id=i.id
            )
            for j in hourlySiteReading:
                total_consumption += j.unit_consumption
        total_consumption = round(total_consumption, 2)
        logger.debug("%s", total_consumption)
        total_energy_savings = total_readings - total_consumption
        total_energy_savings = round(total_energy_savings, 2)
        total_percentage_savings = round(
            (total_energy_savings / total_readings) * 100, 2
        )
        return Response(
            {
                "alarms": alarm,
                "totalConsumption": total_consumption,
                "totalEnergySavings": total_energy_savings,
                "totalPercentageSavings": total_percentage_savings,
            }
        )


class CustomerMonthlyGraphicalData(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s", data)
        customerId = data.get("id", "")
        logger.debug("%s", customerId)
        customerAllSites = Site.objects.filter(customer=customerId).order_by("id")
        logger.debug("%s", customerAllSites)
        currentMonth = datetime.now().date().month
        date = datetime.now().date()
        logger.debug("%s %s", "year", date)
        logger.debug("%s", currentMonth)
        totalData = []
        dateList = []

        for i in range(12):
            logger.debug("%s %s", "i:", i)
            d = date - timedelta(i * 365 / 12)
            dates = d.replace(day=1)
            logger.debug("%s %s", "date", dates)
            total_consumption = 0.0
            for site in customerAllSites:
                logger.debug("%s %s", "site:", site)
                hourlySiteReading = HourlySiteReading.objects.filter(
                    associated_site_id=site.id,
                    reading_from__date__month=currentMonth - i,
                )
                logger.debug("%s %s", "hsr:", hourlySiteReading)
                for j in hourlySiteReading:
                    logger.debug("%s %s", "j:", j)
                    logger.debug("%s %s", "date", j.reading_from)
                    total_consumption += j.unit_consumption
            logger.debug("%s %s", "total consumption:", total_consumption)
            totalData.append(total_consumption)
            dateList.append(dates)
        logger.debug("%s %s", "total data", totalData)
        return Response({"data": totalData, "date": dateList})


class CustomerAllSiteInfo(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        user_id = data.get("id")
        if user_id is None:
            token = request.META.get("HTTP_AUTHORIZATION")
            token = token[6:]
            customer_id = User.objects.only("id", "UserType").get(
                id=Token.objects.get(key=token).user_id
            )
        else:
            customer_id = User.objects.only("id", "UserType").get(id=int(user_id))
        try:
            if customer_id and customer_id.UserType == 5:
                site_manager = CustomerSiteManager.objects.get(customer=customer_id)
                sites = site_manager.associated_site.all().order_by("id")
                serializer = SiteSerializer(sites, many=True)
                return Response(
                    {"result": 1, "site": serializer.data, "msg": "site manager"}
                )
            else:
                sites = Site.objects.filter(customer=customer_id).order_by("id")
                serializer = SiteSerializer(sites, many=True)
                return Response({"result": 1, "site": serializer.data})
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class CustomerSnapshotApiOld(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data%%%%%%%%%%% :", data)
        customer_id = data.get("id", "")
        user_type = data.get("user_type")
        all_site = Site.objects.filter(customer=customer_id, site_type=2)
        live_date = all_site[0].live_date.date()
        logger.debug("%s %s", "live_date :", live_date)
        baseline_date = all_site[0].baseline_date.date()
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        energyConsumed = 0.0
        energySaved = 0.0
        alarm = 0
        for i in all_site:
            alarm += AlarmNotifications.objects.filter(
                site_id=i.id, user_level=4
            ).count()
            if user_type == 1:
                aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=i.id,
                    reading_for__gte=baseline_date,
                    reading_for__lte=previous_date,
                    leg_id__in=all_leg_id,
                )
            else:
                if int(customer_id) == 27:  # for fan separate site
                    logger.debug("%s", "for fan site")
                    aisle_group = AisleGroup.objects.filter(
                        Q(site_id=i.id) & Q(is_visible=True)
                        | Q(attached_leg_id__in=[259, 260, 261])
                    )
                else:
                    logger.debug("%s", "for other customers")
                    aisle_group = AisleGroup.objects.filter(
                        site_id=i.id, is_visible=True
                    )
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=i.id,
                    reading_for__gte=baseline_date,
                    leg_id__in=all_leg_id,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )
            if daily.exists():
                for j in daily:
                    energyConsumed += j.unit_consumption
                    energySaved += j.energy_saved
            else:
                energyConsumed += 0.0
                energySaved += 0.0
        try:
            percentageSaved = (
                str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
            )
        except Exception as e:
            logger.debug("%s %s", "exception is", e)
            percentageSaved = str(0.0) + " %"
        return Response(
            {
                "result": 1,
                "alarms": alarm,
                "energy_consumed": round(energyConsumed, 1),
                "saved_energy": round(energySaved, 1),
                "percentage_saved": percentageSaved,
            }
        )


class CustomerSnapshotApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data%%%%%%%%%%% :", data)
        customer_id = data.get("id", "")
        user_type = data.get("user_type")
        if user_type == 5:
            all_site = CustomerSiteManager.objects.get(customer=customer_id)
            all_site = all_site.associated_site.filter(site_type=2)
        else:
            all_site = Site.objects.filter(customer=customer_id, site_type=2)
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        carbon_visible = False
        carbon_emission_value = 0
        energyConsumed = 0.0
        energySaved = 0.0
        carbon_saved = 0.0
        alarm = 0
        Baseline = 0.0
        for i in all_site:
            live_date = i.live_date.date()
            logger.debug("%s %s", "live_date :", live_date)
            try:
                baseline_date = i.baseline_date.date()
                if i.is_carbon_emission_visible:
                    carbon_emission_value = i.carbon_emission_value
                    carbon_visible = True
            except Exception as err:
                baseline_date = live_date
            # Open alarms of the site (read user_level=4 rows that nothing writes; fixed 2026-11-06).
            alarm += AlarmNotifications.objects.filter(site_id=i.id, is_active=True).count()
            if user_type == 1:
                aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=i.id,
                    reading_for__gte=baseline_date,
                    reading_for__lte=previous_date,
                    leg_id__in=all_leg_id,
                )
            else:
                if int(customer_id) == 27:  # for fan separate site
                    logger.debug("%s", "for fan site")
                    aisle_group = AisleGroup.objects.filter(
                        Q(site_id=i.id) & Q(is_visible=True)
                        | Q(attached_leg_id__in=[259, 260, 261])
                    )
                else:
                    logger.debug("%s", "for other customers")
                    aisle_group = AisleGroup.objects.filter(
                        site_id=i.id, is_visible=True
                    )
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(
                    associated_Site=i.id,
                    reading_for__gte=baseline_date,
                    leg_id__in=all_leg_id,
                    reading_for__lte=previous_date,
                    is_visible=True,
                )
            if daily.exists():
                for j in daily:
                    energyConsumed += j.unit_consumption
                    Baseline += j.daily_baseline_value

            else:
                energyConsumed += 0.0
                energySaved += 0.0
            energySaved = Baseline - energyConsumed
            if carbon_visible:
                carbon_saved += energySaved * carbon_emission_value
            logger.debug("%s %s", "carbon_saved", carbon_saved)
        try:
            percentageSaved = (
                str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
            )
        except Exception as e:
            logger.debug("%s %s", "exception is", e)
            percentageSaved = str(0.0) + " %"
        if energySaved < 0:
            energySaved = 0.0
            percentageSaved = str(0.0) + " %"
        if carbon_saved > 0:
            return Response(
                {
                    "result": 1,
                    "alarms": alarm,
                    "energy_consumed": round(energyConsumed, 1),
                    "saved_energy": round(energySaved, 1),
                    "percentage_saved": percentageSaved,
                    "carbon_saved": round(carbon_saved, 1),
                }
            )
        else:
            return Response(
                {
                    "result": 1,
                    "alarms": alarm,
                    "energy_consumed": round(energyConsumed, 1),
                    "saved_energy": round(energySaved, 1),
                    "percentage_saved": percentageSaved,
                }
            )


class ParticularCustomerInfo(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data in particular customer :", data)
        user_id = data.get("id", "")
        user = User.objects.get(id=user_id).id
        customer = CustomerInfo.objects.get(customer=user)
        serializer = CustomerInfoSerializer(customer)
        return Response({"result": 1, "data": serializer.data})


class TotalAlarmsOnCustomerPageTabularForm(APIView):
    """Customer page table: open alarms per site and type (same keys as before).

    Counted from the open alarms (is_active) of the customer's sites; it used
    to read user_level=4 rows that nothing writes any more, so it was always
    empty (fixed 2026-11-06)."""

    @entryExit
    def post(self, request):
        user = User.objects.get(id=request.data.get("id", ""))
        counts = defaultdict(lambda: defaultdict(int))
        for site_id, alarm_type in AlarmNotifications.objects.filter(
            site_id__customer=user, is_active=True
        ).values_list("site_id", "Alarm_type"):
            counts[site_id][alarm_type] += 1
        names = dict(AlarmNotifications.alarm_type)
        data_list = []
        for site in Site.objects.filter(customer=user, id__in=counts).order_by("id"):
            alarm_list = {names.get(t, str(t)): n for t, n in sorted(counts[site.id].items())}
            data_list.append(
                {
                    "site_id": site.id,
                    "site_name": site.site_name,
                    "alarms": alarm_list,
                    "total_alarm_count": sum(alarm_list.values()),
                    "site_type": site.get_site_type_display(),
                }
            )
        return Response({"result": "1", "data": data_list})


class TotalAlarmsTypeCountOnCustomerPage(APIView):
    """Customer page bar chart: open alarms per type over the customer's sites
    (same keys as before; it used to read rows that nothing writes, fixed
    2026-11-06)."""

    @entryExit
    def post(self, request):
        user = User.objects.get(id=request.data.get("id", ""))
        names = dict(AlarmNotifications.alarm_type)
        per_type = (
            AlarmNotifications.objects.filter(site_id__customer=user, is_active=True)
            .values("Alarm_type").annotate(n=Count("id")).order_by("Alarm_type")
        )
        data_list, alarm_name_list = [], []
        for row in per_type:
            name = names.get(row["Alarm_type"], str(row["Alarm_type"]))
            data_list.append({"name": name, "data": [row["n"]], "type": "column"})
            alarm_name_list.append(name)
        return Response({"result": 1, "Data": data_list, "alarm_name_list": alarm_name_list})

