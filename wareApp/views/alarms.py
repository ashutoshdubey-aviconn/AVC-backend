"""Alarm lists and consumption alarms."""

from datetime import datetime

from django.db.models import Min, Sum
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AlarmNotifications
from wareApp.serializers import AlarmListSerializer


class AlarmsList(APIView):
    """Alarm summary of one site: every alarm type (one alarm table).

    Response unchanged; counts are occurrences (a repeated issue is one row per
    day with a count), so they keep meaning "how many times it happened".
    """

    def post(self, request):
        site = int(request.data.get("siteId"))
        alarms = AlarmNotifications.objects.filter(site_id=site)

        def total(queryset):
            return queryset.aggregate(n=Sum("occurrences"))["n"] or 0

        data = []
        per_type = (
            alarms.values("Alarm_type")
            .annotate(count=Sum("occurrences"), priority=Min("Alarm_priority"))
            .order_by("Alarm_type")
        )
        labels = dict(AlarmNotifications.alarm_priorities)
        names = dict(AlarmNotifications.alarm_type)
        for row in per_type:
            data.append(
                {
                    "name": names.get(row["Alarm_type"], str(row["Alarm_type"])),
                    "count": row["count"] or 0,
                    "priority": labels.get(row["priority"], ""),
                    "alarm_type": row["Alarm_type"],
                }
            )
        return Response(
            {
                "status": 200,
                "total_alarm": total(alarms),
                "high_priority": total(alarms.filter(Alarm_priority=AlarmNotifications.PRIORITY_HIGH)),
                "medium_priority": total(alarms.filter(Alarm_priority=AlarmNotifications.PRIORITY_MEDIUM)),
                "active_alarms": total(alarms.filter(is_active=True)),
                "data": data,
            }
        )


class AlarmsListDetail(APIView):
    """All alarms of one site and type, newest first (same JSON keys as before)."""

    def post(self, request):
        data = request.data
        try:
            alarms = AlarmNotifications.objects.filter(
                site_id=data.get("siteId"), Alarm_type=int(data.get("alarm_type"))
            ).select_related("aisle_group").order_by("-created_time")
            serializer = AlarmListSerializer(alarms, many=True)
            return Response({"status": 200, "data": serializer.data})
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class ConsumptionAlarmsAPI(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = int(data.get("site_id", 0))
            if not site_id:
                return Response({"status": 400, "msg": "site_id is required"})

            alarms_qs = AlarmNotifications.objects.filter(
                site_id=site_id, Alarm_type__in=[7, 8], is_active=True
            )

            start_date_str = data.get("start_date")
            end_date_str = data.get("end_date")

            if start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, "%Y/%m/%d")
                end_date = datetime.strptime(end_date_str, "%Y/%m/%d")
                end_date = end_date.replace(hour=23, minute=59, second=59)
                alarms_qs = alarms_qs.filter(
                    created_time__gte=start_date, created_time__lte=end_date
                )

            alarms_qs = alarms_qs.order_by("-created_time")

            response_data = []
            for alarm in alarms_qs:
                aisle_name = (
                    alarm.aisle_group.aisleGroupName
                    if hasattr(alarm, "aisle_group") and alarm.aisle_group
                    else str(alarm.object_id) if alarm.object_id else ""
                )
                response_data.append(
                    {
                        "id": alarm.id,
                        "alarm_type": alarm.get_Alarm_type_display(),
                        "priority": alarm.get_Alarm_priority_display(),
                        "aisle_group": aisle_name,
                        "created_time": alarm.created_time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )
            return Response({"status": 200, "data": response_data})
        except Exception as e:
            return Response({"status": 500, "msg": str(e)})
