"""Alarm lists and consumption alarms."""

from datetime import datetime

from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AlarmNotifications, NewAlarmsNotifications
from wareApp.serializers import AlarmListSerializer


class AlarmsList(APIView):
    def post(self, request):
        data = request.data
        site = int(data.get("siteId"))
        data = []
        # site = Site.objects.get(id=site_id)
        total_alarms = NewAlarmsNotifications.objects.filter(site_id=site).count()
        high_priority = NewAlarmsNotifications.objects.filter(
            site_id=site, alarm_priority=0
        ).count()
        medium_priority = NewAlarmsNotifications.objects.filter(
            site_id=site, alarm_priority=1
        ).count()
        active_alarms = NewAlarmsNotifications.objects.filter(
            site_id=site, is_active=True
        ).count()
        alarms = NewAlarmsNotifications.objects.filter(site_id=site).distinct(
            "alarm_type"
        )
        for i in alarms:
            count = NewAlarmsNotifications.objects.filter(
                site_id=site, alarm_type=i.alarm_type
            ).count()
            data.append(
                {
                    "name": i.get_alarm_type_display(),
                    "count": count,
                    "priority": i.get_alarm_priority_display(),
                    "alarm_type": i.alarm_type,
                }
            )
        return Response(
            {
                "status": 200,
                "total_alarm": total_alarms,
                "high_priority": high_priority,
                "medium_priority": medium_priority,
                "active_alarms": active_alarms,
                "data": data,
            }
        )


class AlarmsListDetail(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("siteId")
            alarm_type = data.get("alarm_type")
            alarms = NewAlarmsNotifications.objects.filter(
                site_id=site_id, alarm_type=int(alarm_type)
            )
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
