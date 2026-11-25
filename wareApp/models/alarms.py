"""Alarms, alarm settings, fire pump alarms, e-mails and meter disconnections."""

from django.db import models
from django.utils import timezone
from .users import User
from .setup import AisleGroup, Site


class AlarmNotifications(models.Model):
    """Every alarm of every kind (one table since 2026-10, see docs/mqtt-flows).

    One row per issue per day: a repeat updates ``last_seen`` / ``occurrences``
    (and the latest measured values) instead of adding a row. ``last_notified_at``
    throttles the e-mail of alarms that repeat (voltage, PF: every 30 min).
    Scope of the issue: ``aisle_group`` (consumption alarms), ``power_source``
    (voltage / PF / DG) or ``object_type`` + ``object_id`` (meter, gateway).
    Power / DG alarms were stored in a second table (NewAlarmsNotifications)
    until migration 0099 copied them here with the same type numbers; 0103
    dropped that table.
    """

    # Alarm types: one list for all sources, numbers unchanged from the two
    # former tables (power / DG 0-6 and 9 from NewAlarmsNotifications).
    HIGH_VOLTAGE = 0
    LOW_VOLTAGE = 1
    PF_BAD_VALUE = 2
    DG_OVERTIME = 3
    DG_FUEL_UNDER_LEVEL = 4
    MAINS_HIGHER_CONSUMPTION = 5
    FUEL_DRAIN = 6
    HIGH_CONSUMPTION = 7
    LOW_CONSUMPTION = 8
    DG_RUNNING_WITHOUT_LOAD = 9
    METER_READING_ISSUE = 10
    BYPASSED = 11
    OPERATION_HOURS_INCREASED = 12
    GATEWAY_OVERHEAT = 13
    # Data missing (zero-consumption cases 3, 5, 6; wareApp/mqtt/services/gateway_health.py).
    METER_DISCONNECTED = 14
    GATEWAY_DISCONNECTED = 15
    GATEWAY_SERVICE_ISSUE = 16
    CONSUMPTION_SPIKE = 17
    alarm_type = (
        (HIGH_VOLTAGE, "High Voltage"),
        (LOW_VOLTAGE, "Low Voltage"),
        (PF_BAD_VALUE, "PF Bad Value Alarm"),
        (DG_OVERTIME, "DG Overtime"),
        (DG_FUEL_UNDER_LEVEL, "DG Fuel Under Level"),
        (MAINS_HIGHER_CONSUMPTION, "Mains Higher Consumption"),
        (FUEL_DRAIN, "Fuel Drain"),
        (HIGH_CONSUMPTION, "High Consumption"),
        (LOW_CONSUMPTION, "Low Consumption"),
        (DG_RUNNING_WITHOUT_LOAD, "DG Running Without Load"),
        (METER_READING_ISSUE, "Meter Reading Issue"),
        (BYPASSED, "Bypassed"),
        (OPERATION_HOURS_INCREASED, "Operation Hours Increased"),
        (GATEWAY_OVERHEAT, "Gateway Overheat"),
        (METER_DISCONNECTED, "Meter Disconnected"),
        (GATEWAY_DISCONNECTED, "Gateway Disconnected"),
        (GATEWAY_SERVICE_ISSUE, "Gateway Service / Modbus Issue"),
        (CONSUMPTION_SPIKE, "Consumption Spike"),
    )
    POWER_TYPES = frozenset({0, 1, 2, 3, 4, 5, 6, 9})
    CONSUMPTION_TYPES = frozenset({7, 8, 10, 11, 12, 14, 17})
    GATEWAY_TYPES = frozenset({13, 15, 16})

    PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW = 0, 1, 2
    alarm_priorities = ((0, "High"), (1, "Medium"), (2, "Low"))

    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True
    )
    site_id = models.ForeignKey(Site, on_delete=models.CASCADE)
    USER_LEVEL = (
        (1, "Super_Admin"),
        (2, "Aviconn_Admin"),
        (3, "Aviconn_Executive"),
        (4, "Customer"),
        (5, "Cust_Site_Manager"),
    )
    user_level = models.PositiveIntegerField(choices=USER_LEVEL, default=1)
    OBJECT_TYPE = (
        (0, "No_Type"),
        (1, "Sensor"),
        (3, "Light"),
        (4, "Meter"),
        (5, "Gateway"),
    )
    object_type = models.PositiveIntegerField(default=0, choices=OBJECT_TYPE)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    aisle_group = models.ForeignKey(
        "AisleGroup", on_delete=models.CASCADE, null=True, blank=True
    )
    Alarm_type = models.PositiveIntegerField(choices=alarm_type)
    create_DateTime = models.DateTimeField(auto_now=False, auto_now_add=True)
    Alarm_priority = models.PositiveIntegerField(choices=alarm_priorities, default=0)
    created_time = models.DateTimeField(default=timezone.now)
    to_do = models.CharField(max_length=200, blank=True, null=True)
    off_time = models.DateTimeField(default=timezone.now)
    cloud_time = models.DateTimeField(auto_now=False, auto_now_add=True)
    is_active = models.BooleanField(default=True)
    # A repeat of an issue that is already active today updates these
    # instead of adding another row.
    last_seen = models.DateTimeField(blank=True, null=True)
    occurrences = models.PositiveIntegerField(default=1)
    last_notified_at = models.DateTimeField(blank=True, null=True)
    # The alarm's value in its last e-mail (volts, PF, kWh, °C, litres): a
    # repeat is e-mailed again only when it is ALARM_REPEAT_TOLERANCE_PERCENT
    # worse than this (wareApp/mqtt/services/alarm_policy.py).
    notified_value = models.FloatField(blank=True, null=True)
    # Power / DG alarms (voltage, power factor, fuel).
    power_source = models.CharField(max_length=50, blank=True, null=True)
    r_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    y_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    b_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    fuel_level = models.FloatField(blank=True, null=True)
    run_hours = models.FloatField(blank=True, null=True)

    class Meta:
        indexes = [
            # Daily consumption-alarm dedupe: site + aisle + type + time range.
            models.Index(
                fields=["site_id", "aisle_group", "Alarm_type", "created_time"],
                name="idx_alarm_site_aisle_type_time",
            ),
            # Power / DG alarm lookup: site + source + type + time range.
            models.Index(
                fields=["site_id", "power_source", "Alarm_type", "created_time"],
                name="idx_alarmn_site_src_type_time",
            ),
        ]

    @property
    def source(self):
        """'power', 'gateway' or 'consumption' (what raised the alarm)."""
        if self.Alarm_type in self.POWER_TYPES:
            return "power"
        if self.Alarm_type in self.GATEWAY_TYPES:
            return "gateway"
        return "consumption"

    def save(self, *args, **kwargs):
        for name in ("r_phase", "y_phase", "b_phase"):
            value = getattr(self, name)
            if value is not None:
                try:
                    setattr(self, name, round(float(value), 2))
                except (TypeError, ValueError):
                    setattr(self, name, None)
        super().save(*args, **kwargs)

    def __str__(self):
        return "Notification for {}".format(str(self.site_id))


class AlarmSetting(models.Model):
    """How one alarm type behaves on one site.

    Who is e-mailed: wareApp/mqtt/services/alarm_recipients.py (software team,
    ground team per site); ``email_software`` / ``email_ground`` switch a group
    off for this site and type.

    Auto: the system's threshold (baseline, nominal voltage, default PF ...).
    Manual: ``threshold`` (kWh, volts, PF or °C depending on the type).
    Off: the alarm is not raised. Without a row the alarm works as before
    (site fields and defaults).
    """

    AUTO = 1
    MANUAL = 2
    OFF = 3
    MODES = ((AUTO, "Auto"), (MANUAL, "Manual"), (OFF, "Off"))

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="alarm_settings")
    alarm_type = models.PositiveIntegerField(choices=AlarmNotifications.alarm_type)
    mode = models.PositiveSmallIntegerField(choices=MODES, default=AUTO)
    threshold = models.FloatField(
        blank=True,
        null=True,
        help_text="Manual mode: High/Low Voltage in V (all phases), PF Bad Value as "
        "a power factor, High/Low Consumption and Bypassed in kWh per day, "
        "Gateway Overheat in °C.",
    )
    email_software = models.BooleanField(default=True, help_text="E-mail the software team")
    email_ground = models.BooleanField(default=True, help_text="E-mail the site's ground team")
    repeat_tolerance_percent = models.FloatField(
        blank=True,
        null=True,
        help_text="A repeat is e-mailed again only when it is this much worse than the "
        "last e-mailed value (empty: ALARM_REPEAT_TOLERANCE_PERCENT, default 5).",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "alarm_type"], name="uniq_alarm_setting_site_type")
        ]

    def __str__(self):
        return f"{self.site} - {self.get_alarm_type_display()}: {self.get_mode_display()}"


class FirePumpAlarm(models.Model):
    Site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisleGroup = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    r_volt = models.FloatField(null=True, blank=True)
    y_volt = models.FloatField(blank=True, null=True)
    b_volt = models.FloatField(blank=True, null=True)
    Meter_Number = models.PositiveIntegerField(blank=True, null=True)
    motor_status = models.IntegerField(blank=True, null=True)
    auto_mode_updated_time = models.DateTimeField(blank=True, null=True)
    manual_mode_updated_time = models.DateTimeField(blank=True, null=True)
    power_source_updated_time = models.DateTimeField(blank=True, null=True)
    off_mode_time = models.DateTimeField(blank=True, null=True)
    motor_status_time = models.DateTimeField(blank=True, null=True)
    Updated_on = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.aisleGroup.aisleGroupName

    class Meta:
        indexes = [
            models.Index(fields=["Site", "Meter_Number"], name="idx_fpalarm_site_meter")
        ]


class Email_History(models.Model):
    fire_site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    deviceName = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    MODES = (
        (1, "Manual"),
        (2, "Auto"),
        (3, "PowerSource"),
        (4, "OFF"),
        (5, "MotorOn"),
        (6, "sensorByPass"),
    )
    email_for = models.PositiveIntegerField(choices=MODES, null=True, blank=True)
    created = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.fire_site.site_name

    class Meta:
        indexes = [
            models.Index(
                fields=["fire_site", "deviceName", "email_for", "created"],
                name="idx_email_site_dev_kind_time",
            )
        ]


class Email(models.Model):
    fire_site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    deviceName = models.ForeignKey(
        FirePumpAlarm, on_delete=models.CASCADE, null=True, blank=True
    )
    MODES = ((1, "Manual"), (2, "Auto"), (3, "PowerSource"), (4, "OFF"), (5, "MotorOn"))
    email_for = models.PositiveIntegerField(choices=MODES, null=True, blank=True)
    created = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.fire_site.site_name


class MeterDisconnectionEvent(models.Model):
    remote_site_id = models.PositiveIntegerField(null=True, blank=True)
    logged_site_id = models.PositiveIntegerField(null=True, blank=True)
    meter_source_id = models.PositiveIntegerField(null=True, blank=True)

    meter_id = models.PositiveIntegerField()
    meter_number = models.PositiveIntegerField(null=True, blank=True)
    meter_name = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default="disconnected")
    port_id = models.CharField(max_length=100, null=True, blank=True)

    detection_window_start = models.DateTimeField()
    detection_window_end = models.DateTimeField()
    last_seen_at = models.DateTimeField(null=True, blank=True)

    source_log_path = models.CharField(max_length=255, blank=True, default="")
    raw_log_line = models.TextField(null=True, blank=True)

    synced_to_cloud = models.BooleanField(default=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    cloud_response = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("meter_id", "detection_window_start", "detection_window_end")
        ordering = ["-detection_window_end", "meter_id"]

    def __str__(self):
        return "{} {}".format(self.meter_name, self.status)


class PendingEmail(models.Model):
    """An alarm e-mail whose send failed for a passing reason (e.g. the mail
    server refused the login); retried by ``tasks.retry_pending_emails`` with
    back-off for up to NOTIFICATION_RETRY_HOURS, then given up (decided
    2026-11-06, docs/mqtt-flows/EMAIL_RETRIES.md)."""

    function_name = models.CharField(max_length=60)
    args = models.JSONField(default=list)
    summary = models.CharField(max_length=200, blank=True, default="")
    attempts = models.PositiveIntegerField(default=1)
    first_failed_at = models.DateTimeField()
    next_try_at = models.DateTimeField(db_index=True)
    last_error = models.CharField(max_length=300, blank=True, default="")

    def __str__(self):
        return f"{self.function_name}: {self.summary} (attempts {self.attempts})"
