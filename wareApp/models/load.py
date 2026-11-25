"""Live load (LoadData) and its roll-ups, meter sources, power factor."""

from django.db import models
from .setup import AisleGroup, Site


class SiteLoadPower(models.Model):
    """Table wareApp_siteloadpower: site load power. Fields: Associated_Site, Site_Total_Load,
    max_load, min_load, r_volt, y_volt, b_volt, r_current, y_current, b_current, r_power_factor,
    y_power_factor....

    Origin: Ashu (changed from main)
    """
    Associated_Site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    Site_Total_Load = models.FloatField(blank=True, null=True)
    max_load = models.FloatField(default=0, blank=True, null=True)
    min_load = models.FloatField(default=0, blank=True, null=True)
    r_volt = models.FloatField(blank=True, null=True)
    y_volt = models.FloatField(blank=True, null=True)
    b_volt = models.FloatField(blank=True, null=True)
    r_current = models.FloatField(blank=True, null=True)
    y_current = models.FloatField(blank=True, null=True)
    b_current = models.FloatField(blank=True, null=True)
    r_power_factor = models.FloatField(blank=True, null=True)
    y_power_factor = models.FloatField(blank=True, null=True)
    b_power_factor = models.FloatField(blank=True, null=True)
    Supply_Source = models.CharField(max_length=20, null=True, blank=True)
    Meter_Number = models.PositiveIntegerField(null=True, blank=True)
    Status = models.CharField(max_length=10, null=True, blank=True)
    Updated_on = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["Associated_Site", "Updated_on"],
                name="idx_sitepower_site_updated",
            ),
            models.Index(
                fields=["Associated_Site", "Supply_Source", "Meter_Number"],
                name="idx_sitepower_site_src_meter",
            ),
            models.Index(
                fields=["Associated_Site", "Meter_Number"],
                name="idx_sitepower_site_meter",
            ),
        ]

    def __str__(self):
        """Text for this row in admin and logs: 'Total Load: {},R-phase voltage: {}, Y-phase voltage:
        {}, B-phase voltage: {}, R.

        Origin: main (unchanged)
        """
        return (
            "Total Load: {},R-phase voltage: {}, Y-phase voltage: {}, B-phase voltage: {},"
            " R-phase current: {},"
            " Y-phase current: {}, B-phase current: {}, Supply Source: {}".format(
                str(self.Site_Total_Load),
                str(self.r_volt),
                str(self.y_volt),
                str(self.b_volt),
                str(self.r_current),
                str(self.y_current),
                str(self.b_current),
                str(self.Supply_Source),
            )
        )


class MeterSource(models.Model):
    """Table wareApp_metersource: meter source. Fields: Associated_Site, meter_id, meter_number,
    power_source_1, power_source_2, meter_type, is_PS2_valid.

    Origin: Ashu (changed from main)
    """
    Associated_Site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    meter_id = models.PositiveIntegerField(primary_key=True)
    meter_number = models.PositiveIntegerField(null=True, blank=True)
    POWER_SOURCES = (
        (0, "Mains Supply"),
        (1, "DG_1"),
        (2, "DG_2"),
        (3, "DG_3"),
        (4, "DG_4"),
    )
    power_source_1 = models.PositiveIntegerField(
        choices=POWER_SOURCES, null=True, blank=True
    )
    power_source_2 = models.PositiveIntegerField(
        choices=POWER_SOURCES, null=True, blank=True
    )
    METER_TYPE = ((1, "Single Source"), (2, "Dual Source"))
    meter_type = models.PositiveIntegerField(choices=METER_TYPE, null=True, blank=True)
    is_PS2_valid = models.BooleanField(default=False)

    def __str__(self):
        """Text for this row in admin and logs: str(self.power_source_1).

        Origin: main (unchanged)
        """
        return str(self.power_source_1)


class RawLoadData(models.Model):
    # No own index: (site, created) covers site lookups (migration 0111).
    # Telemetry table: no database-level foreign keys (2026-11-06, migration 0113):
    # saves the per-row FK lookup and lock on Site / AisleGroup. Writers look both
    # up first; Django still cascades deletes itself.
    """Table wareApp_rawloaddata: raw load data. Fields: site, aisle_group, load_data, created,
    epoch_time.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False, db_index=False)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False
    )
    load_data = models.FloatField(blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    epoch_time = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["site", "created"], name="idx_rawload_site_created"),
        ]

    def __str__(self):
        """Text for this row in admin and logs: str(self.load_data).

        Origin: main (unchanged)
        """
        return str(self.load_data)


class HourlyLoadData(models.Model):
    # No own index: (site, created) / rollup index covers site lookups (migration 0111).
    # Telemetry table: no database-level foreign keys (2026-11-06, migration 0113):
    # saves the per-row FK lookup and lock on Site / AisleGroup. Writers look both
    # up first; Django still cascades deletes itself.
    """Table wareApp_hourlyloaddata: hourly load data. Fields: site, aisle_group, load_data,
    epoch_time, created, updated_on, is_bypassed.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False, db_index=False)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False
    )
    load_data = models.FloatField(blank=True, null=True)
    epoch_time = models.CharField(max_length=50, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated_on = models.DateTimeField(auto_now=True)
    is_bypassed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["site", "created"], name="idx_load_site_created"),
            models.Index(
                fields=["aisle_group", "created"], name="idx_load_aislegroup_created"
            ),
            models.Index(
                fields=["site", "aisle_group", "created"],
                name="idx_hourlyload_rollup",
            ),
        ]

    def __str__(self):
        """Text for this row in admin and logs: str(self.load_data).

        Origin: main (unchanged)
        """
        return str(self.load_data)


class DailyLoadData(models.Model):
    # Telemetry table: no database-level foreign keys (2026-11-06, migration 0113):
    # saves the per-row FK lookup and lock on Site / AisleGroup. Writers look both
    # up first; Django still cascades deletes itself.
    """Table wareApp_dailyloaddata: daily load data. Fields: site, aisle_group, load_data, epoch_time,
    created, updated_on.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False
    )
    load_data = models.FloatField(blank=True, null=True)
    epoch_time = models.CharField(max_length=50, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["site", "created"], name="idx_dailyload_site_created"),
            models.Index(
                fields=["site", "aisle_group", "created"],
                name="idx_dailyload_rollup",
            ),
        ]

    def __str__(self):
        """Text for this row in admin and logs: str(self.load_data).

        Origin: main (unchanged)
        """
        return str(self.load_data)


class MainsDgLoadData(models.Model):
    # Telemetry table: no database-level foreign keys (2026-11-06, migration 0113):
    # saves the per-row FK lookup and lock on Site / AisleGroup. Writers look both
    # up first; Django still cascades deletes itself.
    """Table wareApp_mainsdgloaddata: mains dg load data. Fields: site, aisle_group, load_data,
    epoch_time, created, updated_on.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False
    )
    load_data = models.FloatField(blank=True, null=True)
    epoch_time = models.CharField(max_length=200, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated_on = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Text for this row in admin and logs: str(self.load_data).

        Origin: main (unchanged)
        """
        return str(self.load_data)


class PowerFactorData(models.Model):
    """Table wareApp_powerfactordata: power factor data. Fields: site, aisle_group, supply_source,
    meter_number, r_phase_pf, y_phase_pf, b_phase_pf, created.

    Origin: main (unchanged)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    supply_source = models.CharField(max_length=20, null=True, blank=True)
    meter_number = models.PositiveIntegerField(null=True, blank=True)
    r_phase_pf = models.FloatField(default=0, blank=True, null=True)
    y_phase_pf = models.FloatField(default=0, blank=True, null=True)
    b_phase_pf = models.FloatField(default=0, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)


class MonthlyMinMaxLoadData(models.Model):
    """Table wareApp_monthlyminmaxloaddata: monthly min max load data. Fields: site, supply_source,
    min_load, min_load_created, max_load, max_load_created, created.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    supply_source = models.CharField(max_length=20, null=True, blank=True)
    min_load = models.FloatField(default=0, blank=True, null=True)
    min_load_created = models.DateTimeField(blank=True, null=True)
    max_load = models.FloatField(default=0, blank=True, null=True)
    max_load_created = models.DateTimeField(blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["site", "supply_source", "created"],
                name="idx_monthlyload_site_src_time",
            ),
        ]

    def __str__(self):
        """Text for this row in admin and logs: self.supply_source.

        Origin: main (unchanged)
        """
        return self.supply_source


class SiteLoadParameters(models.Model):
    """Table wareApp_siteloadparameters: site load parameters. Fields: site_id, parameter_type,
    power_source, meter_number, r_phase, y_phase, b_phase, created.

    Origin: Ashu (changed from main)
    """
    site_id = models.ForeignKey(Site, on_delete=models.CASCADE)
    PARAMETER_TYPE = ((0, "Voltage High"), (1, "Voltage Low"), (2, "Power Factor"))
    parameter_type = models.PositiveIntegerField(
        choices=PARAMETER_TYPE, blank=True, null=True
    )
    power_source = models.CharField(max_length=50, blank=True, null=True)
    meter_number = models.CharField(max_length=10, blank=True, null=True)
    r_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    y_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    b_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # Phases are optional; round only the ones that are set.
        """Rounds the phase values to 2 decimals before saving.

        Origin: Ashu (changed from main)
        """
        for name in ("r_phase", "y_phase", "b_phase"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, round(float(value), 2))
        super().save(*args, **kwargs)

    def __str__(self):
        """Text for this row in admin and logs: 'Notification for {}'.format(str(self.site_id)).

        Origin: main (unchanged)
        """
        return "Notification for {}".format(str(self.site_id))

    class Meta:
        indexes = [
            models.Index(
                fields=["site_id", "power_source", "parameter_type", "created"],
                name="idx_lp_site_src_type_time",
            )
        ]
