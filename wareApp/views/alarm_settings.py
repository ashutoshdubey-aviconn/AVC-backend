"""Alarm settings per site: Auto / Manual / Off, e-mail groups (Super_Admin only).

The same rows as Django admin's AlarmSetting (wareApp/models.py); the alarm code
reads them through wareApp/mqtt/services/alarm_policy.py, whose cache is cleared
on every save / delete, so a change applies within one check.
"""

import logging

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AlarmNotifications, AlarmSetting, Site

__all__ = ["AlarmSettingsApi", "THRESHOLD_UNITS", "NOT_RAISED"]

logger = logging.getLogger(__name__)

# Alarm types whose Manual mode takes a threshold, and its unit. Other types
# take only Auto / Off (Manual without a threshold works as Auto).
THRESHOLD_UNITS = {
    AlarmNotifications.HIGH_VOLTAGE: "V",
    AlarmNotifications.LOW_VOLTAGE: "V",
    AlarmNotifications.PF_BAD_VALUE: "PF",
    AlarmNotifications.HIGH_CONSUMPTION: "kWh / day",
    AlarmNotifications.LOW_CONSUMPTION: "kWh / day",
    AlarmNotifications.BYPASSED: "kWh / day",
    AlarmNotifications.GATEWAY_OVERHEAT: "°C",
    AlarmNotifications.METER_DISCONNECTED: "hours",
    AlarmNotifications.GATEWAY_DISCONNECTED: "hours",
    AlarmNotifications.GATEWAY_SERVICE_ISSUE: "hours",
}
# Types that exist but nothing raises yet (feature N01).
NOT_RAISED = {
    AlarmNotifications.DG_OVERTIME,
    AlarmNotifications.DG_FUEL_UNDER_LEVEL,
    AlarmNotifications.MAINS_HIGHER_CONSUMPTION,
}
MODE_NAMES = {AlarmSetting.AUTO: "auto", AlarmSetting.MANUAL: "manual", AlarmSetting.OFF: "off"}
MODE_VALUES = {name: value for value, name in MODE_NAMES.items()}


def _group(alarm_type):
    if alarm_type in AlarmNotifications.GATEWAY_TYPES:
        return "Gateway"
    if alarm_type in AlarmNotifications.CONSUMPTION_TYPES:
        return "Consumption"
    return "Power"


def _row(alarm_type, name, setting):
    return {
        "alarm_type": alarm_type,
        "alarm_name": name,
        "group": _group(alarm_type),
        "raised": alarm_type not in NOT_RAISED,
        "unit": THRESHOLD_UNITS.get(alarm_type),
        # "default": no row, the alarm works as before (site fields and defaults).
        "mode": MODE_NAMES[setting.mode] if setting else "default",
        "threshold": setting.threshold if setting else None,
        "email_software": setting.email_software if setting else True,
        "email_ground": setting.email_ground if setting else True,
        "repeat_tolerance_percent": setting.repeat_tolerance_percent if setting else None,
    }


def _site(site_id):
    try:
        return Site.objects.get(id=int(site_id))
    except (TypeError, ValueError, Site.DoesNotExist):
        return None


def _flag(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _number(value, field):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number.")


class AlarmSettingsApi(APIView):
    """GET  /api/alarmSettings/?site_id=114  -> every alarm type with its setting on the site.
    POST /api/alarmSettings/ {"site_id": 114, "alarm_type": 7, "mode": "manual", "threshold": 250,
                              "email_software": true, "email_ground": false, "repeat_tolerance_percent": 10}
         mode "default" removes the site's setting (the alarm works as before).
    """

    permission_classes = [IsAuthenticated]

    def _check(self, request):
        if request.user.UserType != 1:
            raise PermissionDenied("Only Super_Admin users can change alarm settings.")

    def _payload(self, site):
        settings = {row.alarm_type: row for row in AlarmSetting.objects.filter(site=site)}
        return {
            "status": 200,
            "site_id": site.id,
            "site_name": site.site_name,
            "data": [_row(t, name, settings.get(t)) for t, name in AlarmNotifications.alarm_type],
        }

    def get(self, request):
        self._check(request)
        site = _site(request.query_params.get("site_id"))
        if site is None:
            return Response({"status": 400, "msg": "Give a valid site_id."}, status=400)
        return Response(self._payload(site))

    def post(self, request):
        self._check(request)
        data = request.data
        site = _site(data.get("site_id"))
        if site is None:
            return Response({"status": 400, "msg": "Give a valid site_id."}, status=400)
        try:
            alarm_type = int(data.get("alarm_type"))
        except (TypeError, ValueError):
            alarm_type = None
        names = dict(AlarmNotifications.alarm_type)
        if alarm_type not in names:
            return Response({"status": 400, "msg": "Give a valid alarm_type."}, status=400)
        mode = str(data.get("mode", "")).strip().lower()
        if mode not in MODE_VALUES and mode != "default":
            return Response({"status": 400, "msg": "mode must be auto, manual, off or default."}, status=400)

        if mode == "default":
            AlarmSetting.objects.filter(site=site, alarm_type=alarm_type).delete()
            logger.info("Alarm setting removed by %s: site=%s type=%s", request.user, site.id, alarm_type)
            return Response(self._payload(site))

        try:
            threshold = _number(data.get("threshold"), "threshold")
            tolerance = _number(data.get("repeat_tolerance_percent"), "repeat_tolerance_percent")
        except ValueError as error:
            return Response({"status": 400, "msg": str(error)}, status=400)
        if mode == "manual":
            if alarm_type not in THRESHOLD_UNITS:
                return Response(
                    {"status": 400, "msg": f"{names[alarm_type]} has no manual threshold: use auto or off."},
                    status=400,
                )
            if threshold is None or threshold <= 0:
                return Response(
                    {"status": 400, "msg": f"Manual needs a threshold above 0 ({THRESHOLD_UNITS[alarm_type]})."},
                    status=400,
                )
        else:
            threshold = None
        if tolerance is not None and tolerance < 0:
            return Response({"status": 400, "msg": "repeat_tolerance_percent can't be negative."}, status=400)

        current = AlarmSetting.objects.filter(site=site, alarm_type=alarm_type).first()
        AlarmSetting.objects.update_or_create(
            site=site, alarm_type=alarm_type,
            defaults={
                "mode": MODE_VALUES[mode],
                "threshold": threshold,
                "email_software": _flag(data.get("email_software"), current.email_software if current else True),
                "email_ground": _flag(data.get("email_ground"), current.email_ground if current else True),
                "repeat_tolerance_percent": tolerance,
            },
        )
        logger.info("Alarm setting saved by %s: site=%s type=%s mode=%s threshold=%s",
                    request.user, site.id, alarm_type, mode, threshold)
        return Response(self._payload(site))
