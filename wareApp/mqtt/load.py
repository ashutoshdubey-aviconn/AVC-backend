import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache

from wareApp import alarm_policy
from wareApp.models import (
    AlarmNotifications,
    AlarmSetting,
    PowerFactorData,
    SiteLoadParameters,
    SiteLoadPower,
)
from wareApp.mqtt.log_context import home_gateway_id_for
from wareApp.mqtt.payloads import KeyValuePayload
from wareApp.mqtt.services.alarms import raise_power_alarm
from wareApp.mqtt.services.failures import TRANSIENT_DB_ERRORS, record_dead_letter
from wareApp.sendmail import (
    send_alarm_for_high_voltage,
    send_alarm_for_low_voltage,
    send_mail_for_pf_fluctuation,
)

logger = logging.getLogger(__name__)

# Voltage / PF alarms: at most one occurrence per source per 30 min; a repeat
# is e-mailed only when it got worse (wareApp/alarm_policy.py).
ALARM_REPEAT = timedelta(minutes=30)


def _site_phase_thresholds(site, names):
    values = tuple(getattr(site, f"{phase}_phase_{names}", None) for phase in "ryb")
    return None if any(value is None for value in values) else values


def _voltage_thresholds(site, parameter_type):
    """R/Y/B thresholds for High (0) / Low (1) Voltage, or None (not checked).

    AlarmSetting Off: not checked; Auto: ALARM_VOLTAGE_AUTO_HIGH / _LOW on every
    phase; Manual: its threshold on every phase, else the site's phase fields.
    Without a setting: the site's fields when show_voltage_alarms is on.
    """
    mode = alarm_policy.mode(site.id, parameter_type)
    if mode == AlarmSetting.OFF:
        return None
    if mode == AlarmSetting.AUTO:
        value = settings.ALARM_VOLTAGE_AUTO_HIGH if parameter_type == 0 else settings.ALARM_VOLTAGE_AUTO_LOW
        return (value,) * 3
    if mode == AlarmSetting.MANUAL:
        manual = alarm_policy.manual_threshold(site.id, parameter_type)
        if manual is not None:
            return (manual,) * 3
    elif not site.show_voltage_alarms:
        return None
    return _site_phase_thresholds(
        site, "voltage_threshold_max" if parameter_type == 0 else "voltage_threshold_min"
    )


def _pf_thresholds(site, values):
    """R/Y/B power-factor thresholds, or None (not checked); same modes as voltage."""
    mode = alarm_policy.mode(site.id, AlarmNotifications.PF_BAD_VALUE)
    if mode == AlarmSetting.OFF:
        return None
    if mode == AlarmSetting.AUTO:
        return (settings.ALARM_PF_AUTO_THRESHOLD,) * 3
    if mode == AlarmSetting.MANUAL:
        manual = alarm_policy.manual_threshold(site.id, AlarmNotifications.PF_BAD_VALUE)
        if manual is not None:
            return (manual,) * 3
    elif not site.is_pf_visible:
        return None
    thresholds = _site_phase_thresholds(site, "pf_threshold")
    if thresholds is None and cache.add(f"pf-thresholds-missing-log:{site.id}", 1, 3600):
        # Once per site per hour instead of on every load packet.
        logger.warning(
            "PF alarm skipped, PF thresholds not configured (logged once per hour): site=%s site_name=%s source=%s meter=%s thresholds r/y/b=%s/%s/%s",
            site.id,
            getattr(site, "site_name", ""),
            values.get("power_source"),
            values.get("meter_number"),
            *(getattr(site, f"{phase}_phase_pf_threshold", None) for phase in "ryb"),
        )
    return thresholds


def _parse_load_message(message):
    fields = KeyValuePayload.parse(message, "load", strip_value_quotes=True)
    value_for = fields.get

    values = {
        "load_power": float(value_for("loadpower", "totalload")),
        "r_volt": float(value_for("rvolt", "rphasevoltage")),
        "y_volt": float(value_for("yvolt", "yphasevoltage")),
        "b_volt": float(value_for("bvolt", "bphasevoltage")),
        "r_current": float(value_for("rcurrent", "rphasecurrent")),
        "y_current": float(value_for("ycurrent", "yphasecurrent")),
        "b_current": float(value_for("bcurrent", "bphasecurrent")),
        "power_source": value_for("powersource"),
        "status": value_for("status"),
        "meter_number": int(value_for("meternumber")),
    }
    power_factor_keys = (
        ("rpowerfactor", "rphasepowerfactor"),
        ("ypowerfactor", "yphasepowerfactor"),
        ("bpowerfactor", "bphasepowerfactor"),
    )
    if all(any(key in fields for key in aliases) for aliases in power_factor_keys):
        values["power_factors"] = (
            float(value_for(*power_factor_keys[0])),
            float(value_for(*power_factor_keys[1])),
            float(value_for(*power_factor_keys[2])),
        )
    return values


def _voltage_alarm_data(site, values, thresholds):
    return {
        "r_volts": round(values["r_volt"], 2),
        "y_volts": round(values["y_volt"], 2),
        "b_volts": round(values["b_volt"], 2),
        "r_volt_threshold": thresholds[0],
        "y_volt_threshold": thresholds[1],
        "b_volt_threshold": thresholds[2],
        "site_id": site.id,
    }


def _record_voltage_alarm(site, values, parameter_type, thresholds):
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
        .order_by("-created")
        .values("r_phase", "y_phase", "b_phase")[:7]
    )
    if len(recent) <= 6:
        return
    if parameter_type == 0:
        violated = all(
            item["r_phase"] > thresholds[0]
            or item["y_phase"] > thresholds[1]
            or item["b_phase"] > thresholds[2]
            for item in recent[:5]
        )
    else:
        violated = all(
            item["r_phase"] < thresholds[0]
            or item["y_phase"] < thresholds[1]
            or item["b_phase"] < thresholds[2]
            for item in recent[:5]
        )
    if not violated:
        return
    # One row per site / source / type / day; at most one occurrence per 30
    # minutes, e-mailed when new or worse (services/alarms.py).
    send = send_alarm_for_high_voltage if parameter_type == 0 else send_alarm_for_low_voltage
    volts = (values["r_volt"], values["y_volt"], values["b_volt"])
    raise_power_alarm(
        site,
        parameter_type,
        power_source=values["power_source"],
        priority=AlarmNotifications.PRIORITY_HIGH,
        values={"r_phase": volts[0], "y_phase": volts[1], "b_phase": volts[2]},
        repeat_every=ALARM_REPEAT,
        email=(send, _voltage_alarm_data(site, values, thresholds)),
        severity=max(volts) if parameter_type == 0 else min(volts),
        worse_when_higher=parameter_type == 0,
    )


def _record_power_factor_alarm(site, values):
    factors = values.get("power_factors")
    if not factors or values["status"] != "ON":
        return
    thresholds = _pf_thresholds(site, values)
    if thresholds is None:
        return
    if not any(value < threshold for value, threshold in zip(factors, thresholds)):
        return
    PowerFactorData.objects.create(
        site=site,
        supply_source=values["power_source"],
        meter_number=values["meter_number"],
        r_phase_pf=factors[0] if factors[0] < thresholds[0] else 0.0,
        y_phase_pf=factors[1] if factors[1] < thresholds[1] else 0.0,
        b_phase_pf=factors[2] if factors[2] < thresholds[2] else 0.0,
        created=datetime.now(),
    )
    raise_power_alarm(
        site,
        AlarmNotifications.PF_BAD_VALUE,
        power_source=values["power_source"],
        priority=AlarmNotifications.PRIORITY_MEDIUM,
        values={"r_phase": factors[0], "y_phase": factors[1], "b_phase": factors[2]},
        repeat_every=ALARM_REPEAT,
        email=(
            send_mail_for_pf_fluctuation,
            {
                "r_pf": factors[0],
                "y_pf": factors[1],
                "b_pf": factors[2],
                "r_pf_threshold": thresholds[0],
                "y_pf_threshold": thresholds[1],
                "b_pf_threshold": thresholds[2],
                "site_id": site.id,
                "power_source": values["power_source"],
            },
        ),
        severity=min(factors),
        worse_when_higher=False,
    )


def handle_load_message(site, location_id, gateway_id, message):
    """Persist real-time load parameters and evaluate legacy voltage/PF alarms."""
    home_gateway_id = home_gateway_id_for(location_id, gateway_id)
    try:
        values = _parse_load_message(message)
        entries = SiteLoadPower.objects.filter(
            Associated_Site=site,
            Supply_Source=values["power_source"],
            Meter_Number=values["meter_number"],
        )
        record_exists = entries.exists()
        if all(values[key] > 0 for key in ("r_volt", "y_volt", "b_volt")):
            for parameter_type in (0, 1):
                thresholds = _voltage_thresholds(site, parameter_type)
                if thresholds is not None:
                    _record_voltage_alarm(site, values, parameter_type, thresholds)

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
        if record_exists:
            _record_power_factor_alarm(site, values)
            factors = values.get("power_factors", (0.0, 0.0, 0.0))
            entries.update(
                **update_values,
                r_power_factor=factors[0],
                y_power_factor=factors[1],
                b_power_factor=factors[2],
            )
            logger.info(
                "Queue1 load reading updated: site=%s home_gateway_id=%s source=%s meter=%s load=%s status=%s updated_at=%s",
                location_id,
                home_gateway_id,
                values["power_source"],
                values["meter_number"],
                values["load_power"],
                values["status"],
                update_values["Updated_on"],
            )
            return (
                f"stored: load source {values['power_source']} meter {values['meter_number']} "
                f"updated load={values['load_power']} status={values['status']}"
            )
        SiteLoadPower.objects.create(
            **update_values,
            min_load=values["load_power"],
            max_load=values["load_power"],
            Supply_Source=values["power_source"],
            Meter_Number=values["meter_number"],
        )
        logger.info(
            "Queue1 load reading created: site=%s home_gateway_id=%s source=%s meter=%s load=%s status=%s created_at=%s",
            location_id,
            home_gateway_id,
            values["power_source"],
            values["meter_number"],
            values["load_power"],
            values["status"],
            update_values["Updated_on"],
        )
        return (
            f"stored: load source {values['power_source']} meter {values['meter_number']} "
            f"created load={values['load_power']} status={values['status']}"
        )
    except TRANSIENT_DB_ERRORS:
        raise
    except Exception as error:
        logger.exception(
            "Queue1 load processing failed: site=%s home_gateway_id=%s",
            location_id,
            home_gateway_id,
        )
        record_dead_letter("load", location_id, gateway_id, message, error)
        return f"failed: {type(error).__name__}: {str(error)[:80]} (dead letter)"
