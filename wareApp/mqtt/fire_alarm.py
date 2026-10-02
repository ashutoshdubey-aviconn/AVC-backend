import logging
from datetime import datetime

from wareApp.models import Email_History, FirePumpAlarm
from wareApp.sendmail import send_mail_fire_alarm_user

logger = logging.getLogger(__name__)


def _parse_fire_alarm_message(message):
    values = message.split("'")[1].split(",")
    return (
        int(values[0].split(":")[1]),
        float(values[1].split(":")[1]),
        float(values[2].split(":")[1]),
        float(values[3].split(":")[1]),
        int(values[4].split(":")[1]),
    )


def _send_fire_alarm_email(site, user_email, device_name, alarm_type, power_status, email_for):
    send_mail_fire_alarm_user(user_email, alarm_type, device_name, power_status)
    Email_History.objects.create(
        fire_site=site,
        deviceName=device_name,
        email_for=email_for,
        created=datetime.now(),
    )


def _send_throttled_motor_on_email(
    site, user_email, device_name, alarm_type, power_status
):
    previous_email = (
        Email_History.objects.filter(
            fire_site=site, deviceName=device_name, email_for=5
        )
        .order_by("-created")
        .first()
    )
    if previous_email and (datetime.now() - previous_email.created).total_seconds() <= 600:
        return
    _send_fire_alarm_email(
        site, user_email, device_name, alarm_type, power_status, email_for=5
    )


def handle_fire_alarm_message(site, location_id, gateway_id, message):
    """Update a fire-pump reading and emit the legacy state-change notifications."""
    try:
        meter_number, r_volt, y_volt, b_volt, power_status = _parse_fire_alarm_message(
            message
        )
        fire_pump_alarm = FirePumpAlarm.objects.filter(
            Site=site, Meter_Number=meter_number
        )
        fire_pump_record = fire_pump_alarm.first()
        if not fire_pump_record:
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
            "Queue1 FIREALARM processing failed for site %s from gateway %s",
            location_id,
            gateway_id,
        )