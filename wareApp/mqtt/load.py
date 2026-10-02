import logging
from datetime import datetime, timedelta

from wareApp.models import (
    NewAlarmsNotifications,
    PowerFactorData,
    SiteLoadParameters,
    SiteLoadPower,
)
from wareApp.sendmail import (
    send_alarm_for_high_voltage,
    send_alarm_for_low_voltage,
    send_mail_for_pf_fluctuation,
)

logger = logging.getLogger(__name__)


def _parse_load_message(message):
    fields = message.split(",")
    values = {
        "load_power": float(fields[0].split(":")[1]),
        "r_volt": float(fields[1].split(":")[1]),
        "y_volt": float(fields[2].split(":")[1]),
        "b_volt": float(fields[3].split(":")[1]),
        "r_current": float(fields[4].split(":")[1]),
        "y_current": float(fields[5].split(":")[1]),
        "b_current": float(fields[6].split(":")[1]),
        "power_source": fields[7].split(":")[1],
        "status": fields[8].split(":")[1],
        "meter_number": int(fields[9].split(":")[1]),
    }
    if len(fields) == 14:
        values["power_factors"] = (
            float(fields[11].split(":")[1]),
            float(fields[12].split(":")[1]),
            float(fields[13].split(":")[1][:-1]),
        )
    return values


def _voltage_alarm_data(site, values, maximum):
    return {
        "r_volts": round(values["r_volt"], 2),
        "y_volts": round(values["y_volt"], 2),
        "b_volts": round(values["b_volt"], 2),
        "r_volt_threshold": site.r_phase_voltage_threshold_max
        if maximum
        else site.r_phase_voltage_threshold_min,
        "y_volt_threshold": site.y_phase_voltage_threshold_max
        if maximum
        else site.y_phase_voltage_threshold_min,
        "b_volt_threshold": site.b_phase_voltage_threshold_max
        if maximum
        else site.b_phase_voltage_threshold_min,
        "site_id": site.id,
    }


def _record_voltage_alarm(site, values, parameter_type):
    SiteLoadParameters.objects.create(
        site_id=site,
        power_source=values["power_source"],
        parameter_type=parameter_type,
        r_phase=values["r_volt"],
        y_phase=values["y_volt"],
        b_phase=values["b_volt"],
        meter_number=values["meter_number"],
        created=datetime.now(),
    )
    recent = list(
        SiteLoadParameters.objects.filter(
            site_id=site,
            power_source=values["power_source"],
            parameter_type=parameter_type,
        )
        .order_by("-created")[:7]
    )
    if len(recent) <= 6:
        return
    thresholds = (
        (site.r_phase_voltage_threshold_max, site.y_phase_voltage_threshold_max, site.b_phase_voltage_threshold_max)
        if parameter_type == 0
        else (site.r_phase_voltage_threshold_min, site.y_phase_voltage_threshold_min, site.b_phase_voltage_threshold_min)
    )
    if parameter_type == 0:
        violated = all(
            item.r_phase > thresholds[0]
            or item.y_phase > thresholds[1]
            or item.b_phase > thresholds[2]
            for item in recent[:5]
        )
    else:
        violated = all(
            item.r_phase < thresholds[0]
            or item.y_phase < thresholds[1]
            or item.b_phase < thresholds[2]
            for item in recent[:5]
        )
    if not violated:
        return
    if NewAlarmsNotifications.objects.filter(
        site_id=site,
        alarm_type=parameter_type,
        power_source=values["power_source"],
        created__gte=datetime.now() - timedelta(minutes=30),
    ).exists():
        return
    NewAlarmsNotifications.objects.create(
        site_id=site,
        alarm_type=parameter_type,
        power_source=values["power_source"],
        created=datetime.now(),
        alarm_priority=0,
        r_phase=values["r_volt"],
        y_phase=values["y_volt"],
        b_phase=values["b_volt"],
    )
    data = _voltage_alarm_data(site, values, maximum=parameter_type == 0)
    if parameter_type == 0:
        send_alarm_for_high_voltage(data)
    else:
        send_alarm_for_low_voltage(data)


def _record_power_factor_alarm(site, values):
    factors = values.get("power_factors")
    if not factors or not site.is_pf_visible or values["status"] != "ON":
        return
    thresholds = (
        site.r_phase_pf_threshold,
        site.y_phase_pf_threshold,
        site.b_phase_pf_threshold,
    )
    if not any(value < threshold for value, threshold in zip(factors, thresholds)):
        return
    PowerFactorData.objects.create(
        site=site,
        supply_source=values["power_source"],
        meter_number=values["meter_number"],
        r_phase_pf=factors[0] if factors[0] < thresholds[0] else None,
        y_phase_pf=factors[1] if factors[1] < thresholds[1] else None,
        b_phase_pf=factors[2] if factors[2] < thresholds[2] else None,
        created=datetime.now(),
    )
    if NewAlarmsNotifications.objects.filter(
        site_id=site,
        power_source=values["power_source"],
        alarm_type=2,
        created__gte=datetime.now() - timedelta(minutes=30),
    ).exists():
        return
    NewAlarmsNotifications.objects.create(
        site_id=site,
        power_source=values["power_source"],
        alarm_type=2,
        alarm_priority=1,
        created=datetime.now(),
        r_phase=factors[0],
        y_phase=factors[1],
        b_phase=factors[2],
    )
    send_mail_for_pf_fluctuation(
        {
            "r_pf": factors[0],
            "y_pf": factors[1],
            "b_pf": factors[2],
            "r_pf_threshold": thresholds[0],
            "y_pf_threshold": thresholds[1],
            "b_pf_threshold": thresholds[2],
            "site_id": site.id,
            "power_source": values["power_source"],
        }
    )


def handle_load_message(site, location_id, gateway_id, message):
    """Persist real-time load parameters and evaluate legacy voltage/PF alarms."""
    try:
        values = _parse_load_message(message)
        entries = SiteLoadPower.objects.filter(
            Associated_Site=site,
            Supply_Source=values["power_source"],
            Meter_Number=values["meter_number"],
        )
        record = entries.first()
        if site.show_voltage_alarms and all(
            values[key] > 0 for key in ("r_volt", "y_volt", "b_volt")
        ):
            _record_voltage_alarm(site, values, parameter_type=0)
            _record_voltage_alarm(site, values, parameter_type=1)
        _record_power_factor_alarm(site, values)

        update_values = {
            "Associated_Site": site,
            "Site_Total_Load": values["load_power"],
            "r_volt": values["r_volt"],
            "y_volt": values["y_volt"],
            "b_volt": values["b_volt"],
            "r_current": values["r_current"],
            "y_current": values["y_current"],
            "b_current": values["b_current"],
            "Status": values["status"],
            "Updated_on": datetime.now(),
        }
        if record:
            factors = values.get("power_factors", (0.0, 0.0, 0.0))
            entries.update(
                **update_values,
                r_power_factor=factors[0],
                y_power_factor=factors[1],
                b_power_factor=factors[2],
            )
            return
        SiteLoadPower.objects.create(
            **update_values,
            min_load=values["load_power"],
            max_load=values["load_power"],
            Supply_Source=values["power_source"],
            Meter_Number=values["meter_number"],
        )
    except Exception:
        logger.exception(
            "Queue1 load processing failed for site %s from gateway %s",
            location_id,
            gateway_id,
        )