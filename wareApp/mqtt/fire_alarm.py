import logging
from datetime import datetime

from wareApp.models import Email_History, FirePumpAlarm
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.services.notifications import notify
from wareApp.sendmail import send_mail_fire_alarm_user

logger = logging.getLogger(__name__)


def _parse_fire_alarm_message(message):
    payload = message.decode("utf-8") if isinstance(message, bytes) else str(message)
    payload = payload.strip()
    if payload.startswith("b'") and payload.endswith("'"):
        payload = payload[2:-1]
    fields = {}
    for field in payload.split(","):
        key, separator, value = field.partition(":")
        if not separator:
            raise ValueError(f"Invalid fire alarm field: {field!r}")
        fields[key.strip().lower().replace("_", "")] = value.strip()

    def value_for(key):
        try:
            return fields[key]
        except KeyError as error:
            raise ValueError(f"Missing fire alarm field: {key}") from error

    return (
        int(value_for("meternumber")),
        float(value_for("rvolt")),
        float(value_for("yvolt")),
        float(value_for("bvolt")),
        int(value_for("powerstatus")),
    )


def _send_fire_alarm_email(
    site, user_email, device_name, alarm_type, power_status, email_for
):
    notify(
        send_mail_fire_alarm_user,
        user_email,
        alarm_type,
        str(device_name),
        power_status,
    )
    Email_History.objects.create(
        fire_site=site,
        deviceName=device_name,
        email_for=email_for,
        created=datetime.now(),
    )


def _send_throttled_motor_on_email(
    site, user_email, device_name, alarm_type, power_status
):
    previous_created = (
        Email_History.objects.filter(
            fire_site=site, deviceName=device_name, email_for=5
        )
        .order_by("-created")
        .values_list("created", flat=True)
        .first()
    )
    if previous_created and (datetime.now() - previous_created).total_seconds() <= 600:
        return
    _send_fire_alarm_email(
        site, user_email, device_name, alarm_type, power_status, email_for=5
    )


def handle_fire_alarm_message(site, location_id, gateway_id, message):
    """Update a fire-pump reading and emit the legacy state-change notifications."""
    home_gateway_id = home_gateway_id_for(location_id, gateway_id)
    try:
        meter_number, r_volt, y_volt, b_volt, power_status = _parse_fire_alarm_message(
            message
        )
        fire_pump_alarm = FirePumpAlarm.objects.filter(
            Site=site, Meter_Number=meter_number
        )
        fire_pump_record = fire_pump_alarm.first()
        if not fire_pump_record:
            logger.warning(
                "Queue1 fire alarm skipped: site=%s home_gateway_id=%s meter=%s reason=no_fire_pump_record",
                location_id,
                home_gateway_id,
                meter_number,
            )
            return

        initial_r_volt = fire_pump_record.r_volt
        initial_y_volt = fire_pump_record.y_volt
        initial_b_volt = fire_pump_record.b_volt
        fire_pump_alarm.update(
            r_volt=r_volt,
            y_volt=y_volt,
            b_volt=b_volt,
            motor_status=power_status,
            Meter_Number=meter_number,
            Updated_on=datetime.now(),
        )
        logger.info(
            "Queue1 fire alarm updated: site=%s home_gateway_id=%s meter=%s power_status=%s r_volt=%s y_volt=%s b_volt=%s",
            location_id,
            home_gateway_id,
            meter_number,
            power_status,
            r_volt,
            y_volt,
            b_volt,
        )
        device_name = fire_pump_record.aisleGroup
        user_email = site.customer.email

        if r_volt > 200 and y_volt < 100 and b_volt > 200 and power_status == 1:
            _send_throttled_motor_on_email(
                site,
                user_email,
                device_name,
                "Motor-On in Auto-Mode",
                power_status,
            )
        if r_volt < 100 and y_volt > 200 and b_volt > 200 and power_status == 1:
            _send_throttled_motor_on_email(
                site,
                user_email,
                device_name,
                "Motor-On in Manual-Mode",
                power_status,
            )
        if (
            r_volt > 200
            and y_volt < 100
            and b_volt > 200
            and initial_r_volt < 100
            and initial_y_volt > 200
            and initial_b_volt > 200
        ):
            _send_fire_alarm_email(
                site,
                user_email,
                device_name,
                "Manual-Mode to Auto-Mode",
                power_status,
                email_for=2,
            )
        elif (
            initial_r_volt > 200
            and initial_y_volt < 100
            and initial_b_volt > 200
            and r_volt < 100
            and y_volt > 200
            and b_volt > 200
        ):
            _send_fire_alarm_email(
                site,
                user_email,
                device_name,
                "Auto-Mode to Manual-Mode",
                power_status,
                email_for=1,
            )
        elif (
            initial_r_volt > 200
            and initial_y_volt < 100
            and initial_b_volt > 200
            and r_volt < 100
            and y_volt < 100
            and b_volt > 200
        ):
            _send_fire_alarm_email(
                site,
                user_email,
                device_name,
                "Auto-Mode to Off-Mode",
                power_status,
                email_for=4,
            )
        elif (
            initial_r_volt < 100
            and initial_y_volt < 100
            and initial_b_volt > 200
            and r_volt < 100
            and y_volt < 100
            and b_volt > 200
        ):
            _send_fire_alarm_email(
                site,
                user_email,
                device_name,
                "Manual-Mode to Off-Mode",
                power_status,
                email_for=4,
            )
        elif (
            initial_r_volt < 100
            and initial_y_volt < 100
            and initial_b_volt > 200
            and r_volt > 200
            and y_volt < 100
            and b_volt > 200
        ):
            _send_fire_alarm_email(
                site,
                user_email,
                device_name,
                "Off-Mode to Auto-Mode",
                power_status,
                email_for=2,
            )
        elif (
            initial_r_volt < 100
            and initial_y_volt < 100
            and initial_b_volt > 200
            and r_volt < 100
            and y_volt > 200
            and b_volt > 200
        ):
            _send_fire_alarm_email(
                site,
                user_email,
                device_name,
                "Off-Mode to Manual-Mode",
                power_status,
                email_for=1,
            )
    except Exception:
        logger.exception(
            "Queue1 FIREALARM processing failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
