"""DG fuel levels, per-run consumption and provider alerts."""

from jsonfield import JSONField
from django.db import models
from .setup import AisleGroup, Site


class DGAlertsData(models.Model):
    """Table wareApp_dgalertsdata: d g alerts data. Fields: created.

    Origin: Ashu (changed from main)
    """
    alert_data = JSONField(default=dict)
    created = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Text for this row in admin and logs: str(self.alert_data).

        Origin: main (unchanged)
        """
        return str(self.alert_data)


class DgFuelConsumptionData(models.Model):
    # No own index: unique (site, vehicle_number, epoch_time) covers site lookups (migration 0111).
    # Telemetry table: no database-level foreign keys (2026-11-06, migration 0113):
    # saves the per-row FK lookup and lock on Site / AisleGroup. Writers look both
    # up first; Django still cascades deletes itself.
    """Table wareApp_dgfuelconsumptiondata: dg fuel consumption data. Fields: site, aisle_group,
    vehicle_number, fuel_consumption, fuel_data_source, epoch_time, created.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False, db_index=False)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    vehicle_number = models.CharField(max_length=50, null=True, blank=True, default=1)
    fuel_consumption = models.FloatField(default=0, null=True, blank=True)
    # Source of the fuel data (e.g. 'loconav' or 'roadcast')
    fuel_data_source = models.CharField(max_length=32, null=True, blank=True)
    epoch_time = models.CharField(max_length=50, null=True, blank=True)
    created = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["site", "created"], name="idx_fuel_site_created"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "vehicle_number", "epoch_time"],
                name="uniq_dgfuel_site_vehicle_epoch",
            )
        ]

    def __str__(self):
        """Text for this row in admin and logs: self.vehicle_number.

        Origin: main (unchanged)
        """
        return self.vehicle_number


class DgUnitConsumption(models.Model):
    """Table wareApp_dgunitconsumption: dg unit consumption. Fields: site, aisle_group,
    unit_consumption, dg_fuel_consumption, dg_start_date, dg_end_date, created, updated_on,
    epoch_time, is_dg_on, fetch_fuel_data, fuel_provider....

    Origin: Ashu (changed from main)
    """
    class DailyDataStatus(models.TextChoices):
        """Status of a DG run's daily data: open, pending, completed or failed.

        Origin: Ashu
        """
        OPEN = "OPEN", "Open"
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    unit_consumption = models.FloatField(default=0, null=True, blank=True)
    dg_fuel_consumption = models.FloatField(default=0, null=True, blank=True)
    dg_start_date = models.DateTimeField(blank=True, null=True)
    dg_end_date = models.DateTimeField(blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated_on = models.DateTimeField(auto_now=True)
    epoch_time = models.CharField(max_length=50, null=True, blank=True)
    is_dg_on = models.BooleanField(default=False)
    fetch_fuel_data = models.BooleanField(default=False)
    fuel_provider = models.CharField(max_length=32, null=True, blank=True)
    fuel_vehicle_number = models.CharField(max_length=50, null=True, blank=True)
    daily_data_status = models.CharField(
        max_length=16,
        choices=DailyDataStatus.choices,
        default=DailyDataStatus.COMPLETED,
    )
    daily_data_retry_count = models.PositiveIntegerField(default=0)
    daily_data_last_attempt_at = models.DateTimeField(blank=True, null=True)
    daily_data_retry_deadline = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        """Text for this row in admin and logs: str(self.unit_consumption).

        Origin: main (unchanged)
        """
        return str(self.unit_consumption)


class DGFuelAlertsData(models.Model):
    """Table wareApp_dgfuelalertsdata: d g fuel alerts data. Fields: site, aisle_group, alert_name,
    vehicle_number, fuel_consumption, epoch_time, created.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.SET_NULL, null=True, blank=True
    )
    alert_name = models.CharField(max_length=50, null=True, blank=True)
    vehicle_number = models.CharField(max_length=50, null=True, blank=True)
    fuel_consumption = models.FloatField(default=0, null=True, blank=True)
    epoch_time = models.CharField(max_length=50, null=True, blank=True)
    created = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        """Text for this row in admin and logs: self.alert_name.

        Origin: main (unchanged)
        """
        return self.alert_name

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "vehicle_number", "alert_name", "epoch_time"],
                name="uniq_dgfuel_alert_site_vehicle_name_epoch",
            )
        ]
