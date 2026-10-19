"""Super-admin customer list, snapshot and alarm summaries."""

from collections import defaultdict
from datetime import datetime

from django.db.models import Count, Q, Sum
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.alarm_feed import active_alarms
from wareApp.models import AlarmNotifications, DailySiteReading, Site, User
from wareApp.utility import logger


class FetchAllCustomersForSuperAdmin(APIView):
    throttle_classes = []
    # authentication_classes = [TokenAuthentication]
    # permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        user_id = data.get("user_id")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        user_obj = None
        if user_id:
            try:
                user_obj = User.objects.filter(id=user_id).first()
            except Exception:
                pass

        default_super_admin_customers = [2, 4, 27, 28, 29, 31, 32, 38, 39, 55, 60, 68]
        allowed_customers_by_user = {
            22: default_super_admin_customers,
        }

        allowed_customer_ids = default_super_admin_customers
        if user_id:
            try:
                uid_int = int(user_id)
                if uid_int in allowed_customers_by_user:
                    allowed_customer_ids = allowed_customers_by_user[uid_int]
            except (ValueError, TypeError):
                pass

        all_users_query = User.objects.filter(UserType=4, id__in=allowed_customer_ids)

        all_users = list(all_users_query.values("id", "username").order_by("id"))
        if not all_users:
            return Response({"data": []})

        customer_ids = [u["id"] for u in all_users]

        site_counts = {
            item["customer_id"]: item
            for item in Site.objects.filter(customer_id__in=customer_ids)
            .values("customer_id")
            .annotate(
                total_sites=Count("id"),
                total_live_sites=Count("id", filter=Q(is_live=True)),
            )
        }

        daily_readings = DailySiteReading.objects.filter(
            associated_Site__customer_id__in=customer_ids,
            associated_Site__is_live=True,
        )
        if start_date is not None and end_date is not None:
            try:
                start_dt = datetime.strptime(start_date, "%Y/%m/%d").date()
                end_dt = datetime.strptime(end_date, "%Y/%m/%d").date()
                daily_readings = daily_readings.filter(
                    reading_for__gte=start_dt, reading_for__lte=end_dt
                )
            except (ValueError, TypeError):
                pass
        else:
            current_date = datetime.now()
            daily_readings = daily_readings.filter(
                reading_for__year=current_date.year,
                reading_for__month=current_date.month,
            )

        readings_by_customer = defaultdict(list)
        for item in daily_readings.values(
            "associated_Site__customer_id", "reading_for"
        ).annotate(sum=Sum("energy_saved"), baseline=Sum("daily_baseline_value")):
            readings_by_customer[item["associated_Site__customer_id"]].append(item)

        response_data = []
        for user in all_users:
            cid = user["id"]
            cname = user["username"]
            customer_readings = readings_by_customer.get(cid, [])

            total_energy_saved = [i.get("sum") or 0 for i in customer_readings]
            total_baseline = [i.get("baseline") or 0 for i in customer_readings]
            total_saved = sum(total_energy_saved)
            total_base = sum(total_baseline)

            average = 0.0
            max_saving = 0.0
            min_saving = 0.0
            if total_saved > 0 and total_base > 0:
                average = (total_saved / total_base) * 100
                max_saved = max(total_energy_saved)
                min_saved = min(total_energy_saved)
                max_baseline = total_baseline[total_energy_saved.index(max_saved)]
                min_baseline = total_baseline[total_energy_saved.index(min_saved)]
                if max_baseline > 0:
                    max_saving = (max_saved / max_baseline) * 100
                if min_baseline > 0:
                    min_saving = (min_saved / min_baseline) * 100

            counts = site_counts.get(cid, {})
            customer_data = {
                "customer_id": cid,
                "customer_name": cname,
                "total_WH": counts.get("total_sites", 0),
                "live_Wh": counts.get("total_live_sites", 0),
                "avg_saving": f"{round(average, 2)} %",
                "max_saving": f"{round(max_saving, 2)} %",
                "min_saving": f"{round(min_saving, 2)} %",
            }
            response_data.append(customer_data)
        return Response({"data": response_data})


class SuperAdminSnapShot(APIView):
    def post(self, request, *args):
        data = request.data
        logger.debug("%s %s", "data : ", data)
        user_id = data.get("user_id")
        start_date = data.get("start_date")
        # date = datetime.strptime(start_date, "%Y/%m/%d")
        # print("date ", date)
        end_date = data.get("end_date")
        current_date = datetime.now()
        previous_date = current_date.replace(day=1)
        date = previous_date.strftime("%Y/%m/%d")
        # enddate = datetime.strptime(end_date, "%Y/%m/%d")
        # print("end_date :",enddate)
        super_user = User.objects.get(id=user_id)
        logger.debug("%s %s", "super_user :", super_user)
        all_users = User.objects.filter(UserType=4)
        all_users_id = [i.id for i in all_users]
        logger.debug("%s %s", "all_user_id : ", all_users_id)
        all_live_sites = Site.objects.filter(customer__in=all_users_id, is_live=True)
        logger.debug("%s %s", "all_live_sites :", all_live_sites)
        all_live_sites_id = [i.id for i in all_live_sites]
        logger.debug("%s %s", "all live sites : ", all_live_sites_id)
        all_alarms = AlarmNotifications.objects.filter(
            site_id__in=all_live_sites_id, is_active=True
        ).count()
        logger.debug("%s", all_alarms)
        counter = 0
        total_percentage_saved = 0
        total_consumed_energy = 0
        total_saved_energy = 0
        for users in all_users:
            logger.debug("%s %s", "users : ", users)
            customer_data = {}
            total_sites = Site.objects.filter(customer=users).count()
            total_live_sites = all_live_sites.count()
            logger.debug("%s %s", "live_sites", total_live_sites)
            all_live_sites_id = [i.id for i in all_live_sites]
            if start_date is not None and end_date is not None:
                start_date = datetime.strptime(start_date, "%Y/%m/%d")
                logger.debug("%s %s", "start_date", start_date)
                end_date = datetime.strptime(end_date, "%Y/%m/%d")
                logger.debug("%s %s", "end_date", end_date)
                d = (
                    DailySiteReading.objects.values("reading_for")
                    .filter(
                        associated_Site__in=all_live_sites_id,
                        reading_for__gte=start_date,
                        reading_for__lte=end_date,
                    )
                    .annotate(
                        leg_count=Count("leg_id"),
                        sum=Sum("energy_saved"),
                        baseline=Sum("daily_baseline_value"),
                    )
                )
                logger.debug("%s %s", "d", d)
            else:
                current_date = datetime.now()
                d = DailySiteReading.objects.filter(
                    associated_Site__in=all_live_sites_id,
                    reading_for__year=current_date.year,
                    reading_for__month=current_date.month,
                ).aggregate(
                    total_energy_saved=Sum("energy_saved"),
                    total_baseline=Sum("daily_baseline_value"),
                    total_unit_consumed=Sum("unit_consumption"),
                )
                logger.debug("%s %s", "output : ", d)
            if (
                d.get("total_energy_saved") is not None
                and d.get("total_energy_saved") > 0
                and d.get("total_baseline") is not None
                and d.get("total_baseline") > 0
            ):
                counter += 1
                total_percentage_saved += (
                    d.get("total_energy_saved") / d.get("total_baseline")
                ) * 100
                logger.debug("%s %s", "total_percentage_saved", total_percentage_saved)
                total_consumed_energy += d.get("total_unit_consumed")
                logger.debug("%s %s", "total_consumed_energy", total_consumed_energy)
                total_saved_energy += d.get("total_energy_saved")
                logger.debug("%s %s", "total_saved_energy", total_saved_energy)

        return Response(
            {
                "current_date": date,
                "alarms": all_alarms,
                "total_unit_consumed": round(total_consumed_energy, 2),
                "total_energy_saved": round(total_saved_energy, 2),
                "total_saved_percentage": str(round(total_percentage_saved, 2)),
            }
        )


class SuperUserAllAlarmsPriorityBasedOnCustomersList(APIView):
    """Active-issue counts per customer, priority and site (one per issue, not per row)."""

    def post(self, request):
        customers = list(User.objects.filter(UserType=4).order_by("id"))
        live_sites = Site.objects.filter(customer__in=customers, is_live=True)
        counts = defaultdict(lambda: defaultdict(int))
        for row in active_alarms(live_sites.values_list("id", flat=True)):
            counts[row["customer_id"]][
                (row["Alarm_priority"], row["site_id__site_name"])
            ] += 1
        response_data = [
            [
                {
                    "Alarm_priority": priority,
                    "site_id__site_name": site_name,
                    "alarm_count": count,
                }
                for (priority, site_name), count in sorted(
                    counts.get(customer.id, {}).items(),
                    key=lambda item: (str(item[0][1]), item[0][0]),
                )
            ]
            for customer in customers
        ]
        return Response({"data": response_data})


class SuperUserAllAlarmsTypeBasedOnCustomersList(APIView):
    """Active alarms of every live site, one row per issue (see wareApp/alarm_feed.py)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.UserType != 1:
            raise PermissionDenied("Only Super_Admin users can view alarms.")

        customers = list(User.objects.filter(UserType=4).order_by("id"))
        live_sites = Site.objects.filter(customer__in=customers, is_live=True)
        by_customer = defaultdict(list)
        for row in active_alarms(live_sites.values_list("id", flat=True)):
            by_customer[row["customer_id"]].append(row)
        response_data = [
            {
                "customer_id": customer.id,
                "customer_name": customer.username,
                "alarm_list": by_customer[customer.id],
            }
            for customer in customers
            if by_customer.get(customer.id)
        ]
        return Response({"data": response_data})
