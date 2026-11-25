"""Energy consumption per aisle: hourly, daily and supply time."""

from django.db.models import Q
from django.db import models
from django.utils import timezone
from .cleaning import CleanReadingMixin
from .setup import AisleGroup, Site


class SupplyLoadTimeShare(models.Model):
    site = models.ForeignKey(Site, related_name="supply", on_delete=models.CASCADE)
    sources = (
        (0, "MAINS SUPPLY"),
        (1, "DG 1"),
        (2, "DG 2"),
        (3, "DG 3"),
        (4, "DG 4"),
        (5, "DG 5"),
    )
    power_source = models.PositiveSmallIntegerField(default=0, choices=sources)
    hourly_run_time = models.IntegerField()
    reading_from = models.DateTimeField(default=timezone.now)
    reading_to = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.get_power_source_display()

    class Meta:
        indexes = [
            models.Index(
                fields=["site", "power_source", "reading_from"],
                name="idx_supply_site_src_time",
            )
        ]


class HourlySiteReading(CleanReadingMixin, models.Model):
    baseline_field = "hourly_baseline_value"

    # No own index: (associated_Site, leg_id, reading_from) covers site lookups (migration 0111).
    associated_Site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True, db_index=False
    )
    # Indexed together with reading_from (idx_hourly_aisle_reading_from, migration 0112).
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True, db_index=False
    )
    leg_id = models.CharField(max_length=50, null=True, blank=True)
    unit_consumption = models.FloatField(default=0)
    hourly_baseline_value = models.FloatField(default=0)
    energy_saved = models.FloatField(default=0)
    reading_from = models.DateTimeField(blank=True, null=True)
    reading_to = models.DateTimeField(blank=True, null=True)
    is_visible = models.BooleanField(default=False)
    # True for an hour created or changed by a catch-up spread (wareApp/catch_up_spread.py):
    # its value is the catch-up hour's kWh shared over the gap, not a meter reading.
    is_estimated = models.BooleanField(default=False)

    class Meta:
        indexes = [
            # Aisle + time: e.g. "is there a reading after the last meter error" (alarm closer).
            models.Index(fields=["aisle_group", "reading_from"], name="idx_hourly_aisle_reading_from"),
            models.Index(
                fields=["associated_Site", "leg_id", "reading_from", "reading_to"],
                name="idx_site_leg_time",
            ),
            models.Index(
                fields=["associated_Site", "leg_id", "reading_from", "reading_to"],
                name="idx_site_leg_time_visible",
                condition=Q(is_visible=True),
            ),
        ]

    def __str__(self):
        return str(self.leg_id)


class DailySiteReading(CleanReadingMixin, models.Model):
    baseline_field = "daily_baseline_value"

    associated_Site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    leg_id = models.CharField(max_length=50, null=True, blank=True)
    unit_consumption = models.FloatField(default=0)
    daily_baseline_value = models.FloatField(default=0)
    energy_saved = models.FloatField(default=0)
    reading_for = models.DateField(blank=True, null=True)
    is_visible = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["associated_Site", "leg_id", "reading_for"],
                name="idx_daily_site_leg_date",
            )
        ]

    def __str__(self):
        return str(self.leg_id)


class SensorAisleUnitConsumption(models.Model):
    associated_Site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    leg_id = models.CharField(max_length=50, null=True, blank=True)
    unit_consumption = models.FloatField(default=0)
    daily_baseline_value = models.FloatField(default=0)
    energy_saved = models.FloatField(default=0)
    reading_for = models.DateTimeField(blank=True, null=True)
    is_visible = models.BooleanField(default=False)

    def __str__(self):
        return str(self.unit_consumption)


class MonthlyLoadSharePercentage(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    sources = (
        (0, "MAINS SUPPLY"),
        (1, "DG 1"),
        (2, "DG 2"),
        (3, "DG 3"),
        (4, "DG 4"),
        (5, "DG 5"),
    )
    power_source = models.PositiveSmallIntegerField(default=0, choices=sources)
    monthly_time_based_percentage = models.PositiveIntegerField(default=0)
    monthly_energy_based_percentage = models.PositiveIntegerField(default=0)
    for_month = models.CharField(max_length=50, null=True, blank=True)
    created_on = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return str(self.time_based_percentage)


class MeterReadings(models.Model):
    local_meterId = models.PositiveIntegerField(null=True, blank=True)
    reading_type = ((0, "Energy"), (1, "Load_time"), (2, "Sensor"))
    reading_for = models.PositiveIntegerField(
        choices=reading_type, null=True, blank=True
    )
    reading_of = models.CharField(max_length=100, null=True, blank=True)
    previous_reading_value = models.CharField(max_length=100, null=True, blank=True)
    updated_on = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.reading_of
