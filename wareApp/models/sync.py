"""Sync / recovery state, gateway status and catch-up spreads."""

from django.db import models
from django.utils import timezone
from .setup import AisleGroup, HomeGatewayId, Site


class RecoveryMonitor(models.Model):
    """Table wareApp_recoverymonitor: recovery monitor. Fields: site, gateway_id, aisle_group, leg_id,
    power_source, recovery_type, status, missing_from, missing_to, expected_slots, recovered_slots,
    error_slots....

    Origin: Ashu
    """
    RECOVERY_TYPES = (
        ("hourly_consumption", "Hourly Consumption"),
        ("daily_consumption", "Daily Consumption"),
        ("load_runtime", "Load Runtime"),
    )
    STATUSES = (
        ("requested", "Requested"),
        ("response_received", "Response Received"),
        ("applied", "Applied"),
        ("verified", "Verified"),
        ("failed", "Failed"),
        ("timeout", "Timeout"),
    )

    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    gateway_id = models.CharField(max_length=100, blank=True, null=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.SET_NULL, blank=True, null=True
    )
    leg_id = models.CharField(max_length=50, blank=True, null=True)
    power_source = models.IntegerField(blank=True, null=True)
    recovery_type = models.CharField(max_length=30, choices=RECOVERY_TYPES)
    status = models.CharField(max_length=30, choices=STATUSES, default="requested")
    missing_from = models.DateTimeField()
    missing_to = models.DateTimeField(blank=True, null=True)
    expected_slots = models.IntegerField(default=0)
    recovered_slots = models.IntegerField(default=0)
    error_slots = models.IntegerField(default=0)
    mqtt_request_topic = models.CharField(max_length=255, blank=True, null=True)
    mqtt_request_payload = models.TextField(blank=True, null=True)
    mqtt_response_payload = models.TextField(blank=True, null=True)
    requested_at = models.DateTimeField(default=timezone.now)
    response_received_at = models.DateTimeField(blank=True, null=True)
    applied_at = models.DateTimeField(blank=True, null=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    failed_reason = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    # Request attempts for the same gap (retried after each cooldown).
    attempt = models.PositiveSmallIntegerField(default=1)
    # First hour that carries the consumption of an outage reported as
    # ERROR404 (the meter's cumulative difference lands here). Alarms skip it.
    catch_up_at = models.DateTimeField(blank=True, null=True)
    # Hour starts ("YYYY-MM-DDTHH:MM:SS") the gateway answered ERROR404 for (no data on
    # the gateway, stored as 0 kWh). Lets a catch-up spread fill exactly those hours
    # (wareApp/catch_up_spread.py); real 0 kWh hours are never taken for them.
    error_hours = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["site", "recovery_type", "status"],
                name="idx_recovery_site_status",
            ),
            # Latest monitor of an aisle / source: filter + newest first in
            # one index (was a backward scan over every monitor, ~11 ms).
            models.Index(
                fields=["site", "leg_id", "recovery_type", "requested_at"],
                name="idx_recovery_site_leg_time",
            ),
            models.Index(
                fields=["site", "power_source", "recovery_type", "requested_at"],
                name="idx_recovery_site_src_time",
            ),
            models.Index(
                fields=["requested_at", "is_active"], name="idx_recovery_active_time"
            ),
        ]
        ordering = ["-requested_at"]

    def __str__(self):
        """Text for this row in admin and logs: '{} {} {}'.format(self.site, self.recovery_type,
        self.status).

        Origin: Ashu
        """
        return "{} {} {}".format(self.site, self.recovery_type, self.status)


class AisleSyncRecoveryStatus(models.Model):
    """Table wareApp_aislesyncrecoverystatus: aisle sync recovery status. Fields: site,
    home_gateway_id, aisle_group, power_source, leg_id, sync_status, is_sync_gone,
    recovery_requested, recovery_received, last_sync_at, last_recovery_requested_at,
    last_recovery_received_at....

    Origin: Ashu
    """
    SYNC_STATUSES = (
        ("unknown", "Unknown"),
        ("healthy", "Healthy"),
        ("late", "Late"),
        ("missing", "Missing"),
        ("recovery_requested", "Recovery Requested"),
        ("recovery_received", "Recovery Received"),
        ("recovered", "Recovered"),
        ("failed", "Failed"),
    )

    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    home_gateway_id = models.CharField(max_length=200)
    # Consumption status rows are per aisle group; SupplyTime / loadRuntime
    # status rows are per power source (aisle_group empty).
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, blank=True, null=True
    )
    power_source = models.IntegerField(blank=True, null=True)
    leg_id = models.CharField(max_length=50, blank=True, default="")
    sync_status = models.CharField(
        max_length=30, choices=SYNC_STATUSES, default="unknown"
    )
    is_sync_gone = models.BooleanField(default=False)
    recovery_requested = models.BooleanField(default=False)
    recovery_received = models.BooleanField(default=False)
    last_sync_at = models.DateTimeField(blank=True, null=True)
    last_recovery_requested_at = models.DateTimeField(blank=True, null=True)
    last_recovery_received_at = models.DateTimeField(blank=True, null=True)
    last_recovery_applied_at = models.DateTimeField(blank=True, null=True)
    expected_from = models.DateTimeField(blank=True, null=True)
    expected_to = models.DateTimeField(blank=True, null=True)
    missing_slots = models.PositiveIntegerField(default=0)
    recovered_slots = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)
    # Recovered, but some hours were ERROR404 (no data on the gateway).
    has_data_loss = models.BooleanField(default=False)
    recovery_monitor = models.ForeignKey(
        RecoveryMonitor,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="current_statuses",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "home_gateway_id", "aisle_group"],
                condition=models.Q(aisle_group__isnull=False),
                name="uniq_sync_status_site_gateway_aisle",
            ),
            models.UniqueConstraint(
                fields=["site", "home_gateway_id", "power_source"],
                condition=models.Q(aisle_group__isnull=True),
                name="uniq_sync_status_site_gateway_source",
            ),
        ]
        indexes = [
            models.Index(
                fields=["site", "sync_status"], name="idx_sync_status_site_state"
            ),
            models.Index(
                fields=["site", "leg_id"], name="idx_sync_status_site_leg"
            ),
        ]

    def __str__(self):
        """Text for this row in admin and logs: '{} {} {}'.format(self.site, self.leg_id,
        self.sync_status).

        Origin: Ashu
        """
        return "{} {} {}".format(self.site, self.leg_id, self.sync_status)


class HomeGatewayStatus(models.Model):
    """Table wareApp_homegatewaystatus: home gateway status. Fields: home_gateway, latitude, longitude,
    status, last_ping_at, last_data_at.

    Origin: Ashu
    """
    home_gateway = models.ForeignKey(
        HomeGatewayId, on_delete=models.CASCADE, related_name="locations"
    )
    latitude = models.DecimalField(
        max_digits=20, decimal_places=15, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=20, decimal_places=15, null=True, blank=True
    )
    status = models.BooleanField(default=True)
    # Gateway health (wareApp/mqtt/services/gateway_health.py): last PINGREQ /
    # connection seen in the Mosquitto log, and last data packet (consumption,
    # recovery, load, LoadData) seen by our MQTT listeners.
    last_ping_at = models.DateTimeField(blank=True, null=True)
    last_data_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        """Text for this row in admin and logs: f"{(self.home_gateway.hgw_id if self.home_gateway else
        'No Gateway')} - ({self.l.

        Origin: Ashu
        """
        return f"{self.home_gateway.hgw_id if self.home_gateway else 'No Gateway'} - ({self.latitude}, {self.longitude})"


class CatchUpSpread(models.Model):
    """One catch-up hour spread over the data gap before it (wareApp/catch_up_spread.py,
    POST /api/catchUpSpread/; decided 2026-11-16, reworked 2026-11-20: spread hours are
    real readings, manual or automatic, undo for 5 days). Kept for the record and for undo.

    Origin: Ashu
    """

    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    aisle_group = models.ForeignKey(AisleGroup, on_delete=models.CASCADE)
    leg_id = models.CharField(max_length=50)
    catch_up_at = models.DateTimeField()
    original_kwh = models.FloatField()
    gap_from = models.DateTimeField()
    hours = models.PositiveIntegerField()  # the catch-up hour + the missing hours
    share_kwh = models.FloatField()
    applied_by = models.CharField(max_length=150, blank=True, default="")
    applied_at = models.DateTimeField(auto_now_add=True)
    undone_at = models.DateTimeField(null=True, blank=True)
    MANUAL, AUTOMATIC = "manual", "automatic"
    mode = models.CharField(max_length=10, choices=((MANUAL, "Manual"), (AUTOMATIC, "Automatic")), default=MANUAL)
    # One entry per hour of the spread, for checking and for undo:
    # {"at": "YYYY-MM-DDTHH:MM:SS", "kind": "empty" | "no_data" | "catch_up", "before": kWh or null, "after": kWh}
    # empty = no row (created), no_data = ERROR404 row stored as 0, catch_up = the catch-up hour.
    hours_detail = models.JSONField(default=list, blank=True)

    def __str__(self):
        """Text for this row in admin and logs: f'site {self.site_id} leg {self.leg_id}
        {self.catch_up_at:%Y-%m-%d %H:%M}: {self.

        Origin: Ashu
        """
        return f"site {self.site_id} leg {self.leg_id} {self.catch_up_at:%Y-%m-%d %H:%M}: {self.original_kwh} kWh / {self.hours} h"
