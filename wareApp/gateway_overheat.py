"""Gateway overheat alerts sent by the gateways' temperature monitor.

The gateway script (recovery_gateway_live/temperature.py on the gateways)
POSTs to /api/temp/dispatch/mail/ while the CPU is at or above 85 °C, every
few seconds, with this JSON body::

    {"Site Id": 71, "Site Name": "...", "Site Type": "...", "Gateway No": "2",
     "Gateway Info": {"Temperature": 87.3, "CPU Status": {...}, "Fan PWM": ...}}

Each alert becomes an AlarmNotifications row (Alarm_type 13, object_type
Gateway): one row per site and gateway per day; repeats update last_seen /
occurrences and the latest reading. Storage is throttled per gateway and the
alarm e-mail is sent at most once per gateway per GATEWAY_OVERHEAT_EMAIL_SECONDS.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from wareApp.models import AlarmNotifications, Site
from wareApp.mqtt.services.notifications import notify
from wareApp.sendmail import send_alarm_email

logger = logging.getLogger(__name__)

GATEWAY_OVERHEAT_ALARM_TYPE = 13
GATEWAY_OBJECT_TYPE = 5
DEFAULT_THRESHOLD_C = 85.0


class InvalidOverheatAlert(ValueError):
    """The request body is not a usable overheat alert."""


@dataclass(frozen=True)
class OverheatAlert:
    site_id: int
    gateway_no: str
    temperature: float
    cpu_status: str
    fan_pwm: str


def _text(value, limit=60):
    if isinstance(value, dict):
        value = ", ".join(f"{k}: {v}" for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    return str(value if value is not None else "-")[:limit]


def parse_alert(data):
    """Validate the gateway's JSON body; raise InvalidOverheatAlert."""
    if not isinstance(data, dict):
        raise InvalidOverheatAlert("body must be a JSON object")
    try:
        site_id = int(data.get("Site Id"))
    except (TypeError, ValueError):
        raise InvalidOverheatAlert("'Site Id' must be a number")
    info = data.get("Gateway Info")
    if not isinstance(info, dict):
        raise InvalidOverheatAlert("'Gateway Info' must be an object")
    try:
        temperature = float(info.get("Temperature"))
    except (TypeError, ValueError):
        raise InvalidOverheatAlert("'Gateway Info.Temperature' must be a number")
    gateway_no = str(data.get("Gateway No") or "").strip()[:20] or "?"
    return OverheatAlert(
        site_id=site_id,
        gateway_no=gateway_no,
        temperature=round(temperature, 1),
        cpu_status=_text(info.get("CPU Status")),
        fan_pwm=_text(info.get("Fan PWM"), 30),
    )


def record_overheat(alert):
    """Store (or count) the alarm and e-mail it at most once per window.

    Returns a short outcome text. Raises Site.DoesNotExist for unknown sites.
    """
    site = Site.objects.get(id=alert.site_id)
    gateway_key = f"{alert.site_id}:{alert.gateway_no}"
    store_every = getattr(settings, "GATEWAY_OVERHEAT_STORE_SECONDS", 60)
    if not cache.add(f"gateway-overheat-store:{gateway_key}", 1, store_every):
        return "throttled"

    now = timezone.now()
    day_start = datetime.combine(now.date(), datetime.min.time())
    detail = (
        f"Gateway {alert.gateway_no}: CPU {alert.temperature} °C "
        f"(fan PWM {alert.fan_pwm})"
    )[:200]
    repeated = AlarmNotifications.objects.filter(
        site_id=site,
        object_type=GATEWAY_OBJECT_TYPE,
        object_id=_gateway_number(alert.gateway_no),
        Alarm_type=GATEWAY_OVERHEAT_ALARM_TYPE,
        is_active=True,
        created_time__gte=day_start,
    ).update(last_seen=now, occurrences=F("occurrences") + 1, to_do=detail)
    if not repeated:
        AlarmNotifications.objects.create(
            created_by=None,
            user_level=2,
            site_id=site,
            object_type=GATEWAY_OBJECT_TYPE,
            object_id=_gateway_number(alert.gateway_no),
            Alarm_type=GATEWAY_OVERHEAT_ALARM_TYPE,
            Alarm_priority=1,
            created_time=now,
            last_seen=now,
            to_do=detail,
        )

    email_every = getattr(settings, "GATEWAY_OVERHEAT_EMAIL_SECONDS", 3600)
    emailed = cache.add(f"gateway-overheat-email:{gateway_key}", 1, email_every)
    if emailed:
        notify(
            send_alarm_email,
            "Gateway Overheat",
            site.id,
            [
                ["Gateway", alert.gateway_no, False],
                ["CPU temperature", f"{alert.temperature} °C", True],
                ["CPU frequency", alert.cpu_status, False],
                ["Fan PWM", alert.fan_pwm, False],
                ["Threshold", f"{DEFAULT_THRESHOLD_C} °C", False],
            ],
        )
    logger.warning(
        "Gateway overheat %s: site=%s gateway_no=%s temperature=%s fan_pwm=%s emailed=%s",
        "repeated" if repeated else "stored",
        alert.site_id,
        alert.gateway_no,
        alert.temperature,
        alert.fan_pwm,
        emailed,
    )
    return "repeated" if repeated else "stored"


def _gateway_number(gateway_no):
    return int(gateway_no) if gateway_no.isdigit() else None
