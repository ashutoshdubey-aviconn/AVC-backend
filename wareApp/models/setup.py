"""Customers, sites, aisle groups, gateways and baselines."""

from django.db import models
from django.db.models.signals import post_save
from django.conf import settings
from .users import User


class CustomerInfo(models.Model):
    """Table wareApp_customerinfo: customer info. Fields: customer, address, created_by,
    total_energy_consumed, total_energy_saved, total_sites.

    Origin: Ashu (changed from main)
    """
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="customer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    address = models.CharField(max_length=30, null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True
    )

    total_energy_consumed = models.FloatField(default=0)
    total_energy_saved = models.FloatField(default=0)
    total_sites = models.PositiveIntegerField(default=0)

    def __str__(self):
        """Text for this row in admin and logs: self.customer.username.

        Origin: main (unchanged)
        """
        return self.customer.username


class Site(models.Model):
    """Table wareApp_site: site. Fields: customer, site_name, site_type, total_no_of_blocks,
    total_no_of_aisles, location, per_unit_cost, genset_unit_rate, no_of_single_source_meters,
    no_of_dual_source_meters, is_active, is_visible....

    Origin: Ashu (changed from main)
    """
    customer = models.ForeignKey(
        User, related_name="site", on_delete=models.CASCADE, null=True, blank=True
    )
    site_name = models.CharField(max_length=50)
    SITE_TYPE = (
        (1, "WH_Metering"),
        (2, "WH_Energy_Saving"),
        (3, "Fire_monitoring_system"),
        (4, "FEMS"),
        (5, "WH_SubMetering"),
    )
    site_type = models.PositiveIntegerField(choices=SITE_TYPE, null=True, blank=True)
    total_no_of_blocks = models.PositiveIntegerField(null=True, blank=True)
    total_no_of_aisles = models.PositiveIntegerField(null=True, blank=True)
    location = models.CharField(max_length=250, null=True, blank=True)
    per_unit_cost = models.FloatField(null=True, blank=True)
    genset_unit_rate = models.FloatField(null=True, blank=True)
    no_of_single_source_meters = models.PositiveIntegerField(null=True, blank=True)
    no_of_dual_source_meters = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(null=True, blank=True)
    is_visible = models.BooleanField(null=True, blank=True)
    is_live = models.BooleanField(default=False)
    live_date = models.DateTimeField(null=True, blank=True)
    baseline_date = models.DateTimeField(null=True, blank=True)
    current_baseline = models.FloatField(null=True, blank=True)
    consumed_energy = models.FloatField(null=True, blank=True)
    total_energy_saved = models.FloatField(null=True, blank=True)
    site_manager = models.CharField(max_length=50, null=True, blank=True)
    site_manager_contact = models.CharField(max_length=50, null=True, blank=True)
    site_manager_email = models.EmailField(max_length=50, null=True, blank=True)
    avg_saving = models.FloatField(null=True, blank=True)
    max_saving = models.FloatField(null=True, blank=True)
    min_saving = models.FloatField(null=True, blank=True)
    max_threshold_value = models.FloatField(blank=True, null=True)
    min_threshold_value = models.FloatField(blank=True, null=True)
    nl_operation_hours = models.PositiveSmallIntegerField(blank=True, null=True)
    nl_operation_start_time = models.TimeField(blank=True, null=True)
    nl_operation_end_time = models.TimeField(blank=True, null=True)
    high_consumption_units = models.FloatField(blank=True, null=True)
    bypass_consumption_units = models.FloatField(blank=True, null=True)
    high_consumption_baseline_percent = models.FloatField(blank=True, null=True)
    is_pf_visible = models.BooleanField(default=False)
    is_loadGraph_visible = models.BooleanField(default=False)
    show_dg_mains_run_time = models.BooleanField(default=False)
    dg_fuel_system_installed = models.BooleanField(default=False)
    customer_visible_dg_fuel_data = models.BooleanField(default=False)
    customer_dg_fuel_visible_date = models.DateTimeField(null=True, blank=True)
    partner_dg_fuel_id = models.CharField(max_length=50, null=True, blank=True)
    # Explicit provider for DG fuel data ('loconav' or 'roadcast')
    partner_dg_provider = models.CharField(max_length=32, null=True, blank=True)
    r_phase_pf_threshold = models.FloatField(default=0, blank=True, null=True)
    y_phase_pf_threshold = models.FloatField(default=0, blank=True, null=True)
    b_phase_pf_threshold = models.FloatField(default=0, blank=True, null=True)
    is_carbon_emission_visible = models.BooleanField(default=False)
    carbon_emission_value = models.FloatField(default=0, null=True, blank=True)
    is_hourly_data_visible_customer = models.BooleanField(default=False)
    is_alarm_History_active = models.BooleanField(default=False)
    show_voltage_alarms = models.BooleanField(default=False)
    r_phase_voltage_threshold_max = models.FloatField(null=True, blank=True)
    y_phase_voltage_threshold_max = models.FloatField(null=True, blank=True)
    b_phase_voltage_threshold_max = models.FloatField(null=True, blank=True)
    r_phase_voltage_threshold_min = models.FloatField(null=True, blank=True)
    y_phase_voltage_threshold_min = models.FloatField(null=True, blank=True)
    b_phase_voltage_threshold_min = models.FloatField(null=True, blank=True)
    r_phase_pf_threshold = models.FloatField(null=True, blank=True)
    y_phase_pf_threshold = models.FloatField(null=True, blank=True)
    b_phase_pf_threshold = models.FloatField(null=True, blank=True)
    dg_fuel_tank_capacity = models.FloatField(null=True, blank=True)
    dg_fuel_minimum_level = models.FloatField(null=True, blank=True)
    dg_overtime = models.FloatField(blank=True, null=True)  # in minutes

    class Meta:
        indexes = [
            models.Index(
                fields=["customer", "dg_fuel_system_installed"],
                name="idx_customer_dg_fuel",
            ),
            models.Index(fields=["customer", "is_live"], name="idx_customer_is_live"),
        ]

    def __str__(self):
        """Text for this row in admin and logs: f'{self.site_name} ({self.id})' if self.site_name else
        f'Site {self.id}'.

        Origin: Ashu
        """
        return f"{self.site_name} ({self.id})" if self.site_name else f"Site {self.id}"


class CustomerSiteManager(models.Model):
    """Table wareApp_customersitemanager: customer site manager. Fields: customer, created_by,
    associated_site, created.

    Origin: Ashu (changed from main)
    """
    customer = models.ForeignKey(
        User,
        related_name="customerSiteManager",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True
    )
    associated_site = models.ManyToManyField(Site, blank=True)
    created = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        """Text for this row in admin and logs: f'CustomerSiteManager {self.pk}'.

        Origin: Ashu
        """
        if self.customer:
            full_name = self.customer.get_full_name().strip()
            return full_name or self.customer.username
        return f"CustomerSiteManager {self.pk}"


class HomeGatewayId(models.Model):
    """Table wareApp_homegatewayid: home gateway id. Fields: hgw_id, owned_by, connected_to, rssh_port,
    monitoring_port.

    Origin: Ashu (changed from main)
    """
    hgw_id = models.CharField(max_length=200)
    owned_by = models.ForeignKey(
        CustomerInfo,
        related_name="owned_by",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    connected_to = models.ForeignKey(
        Site,
        related_name="connected_to",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    rssh_port = models.CharField(max_length=10, unique=True, blank=True, null=True)
    monitoring_port = models.CharField(
        max_length=10, unique=True, blank=True, null=True
    )

    def __str__(self):
        """Text for this row in admin and logs: self.hgw_id.

        Origin: main (unchanged)
        """
        return self.hgw_id


class Image(models.Model):
    """Table wareApp_image: image. Fields: which_site, image_file, image_id.

    Origin: Ashu (changed from main)
    """
    which_site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    image_file = models.FileField()
    image_id = models.CharField(max_length=10)

    def __str__(self):
        """Text for this row in admin and logs: self.image_file.

        Origin: main (unchanged)
        """
        return self.image_file


class BlockInfo(models.Model):
    """Table wareApp_blockinfo: block info. Fields: block_name, site_id, is_active.

    Origin: Ashu (changed from main)
    """
    block_name = models.CharField(max_length=50)
    site_id = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    is_active = models.BooleanField()

    def __str__(self):
        """Text for this row in admin and logs: self.block_name + ' ' + str(self.site_id).

        Origin: main (unchanged)
        """
        return self.block_name + " " + str(self.site_id)


class Panel(models.Model):
    """Table wareApp_panel: panel. Fields: site, panel.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    panel = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        """Text for this row in admin and logs: self.panel + ' ' + str(self.site).

        Origin: main (unchanged)
        """
        return self.panel + " " + str(self.site)


class Floor(models.Model):
    """Table wareApp_floor: floor. Fields: site, floor.

    Origin: Ashu (changed from main)
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    FLOOR = (
        ("GF", "Ground Floor"),
        ("F1", "First Floor"),
        ("F2", "Second Floor"),
        ("F3", "Third Floor"),
        ("F4", "Fourth Floor"),
        ("F5", "Fifth Floor"),
    )
    floor = models.CharField(max_length=30, choices=FLOOR, null=True, blank=True)

    def __str__(self):
        """Text for this row in admin and logs: self.floor + ' ' + str(self.site).

        Origin: main (unchanged)
        """
        return self.floor + " " + str(self.site)


class AisleGroup(models.Model):
    """Table wareApp_aislegroup: aisle group. Fields: site, attached_leg_id, block_id, panel, floor,
    aisleGroupName, total_lights, one_light_watt, expected_consumption, cumulative_consumption,
    on_sensor_power, is_active....

    Origin: Ashu (changed from main)
    """
    class DgFuelProvider(models.TextChoices):
        """Fuel providers a DG aisle can use: LocoNav or Roadcast.

        Origin: Ashu
        """
        LOCONAV = "loconav", "LocoNav"
        ROADCAST = "roadcast", "Roadcast"

    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    attached_leg_id = models.CharField(max_length=30, null=True, blank=True)
    block_id = models.ManyToManyField(BlockInfo)
    panel = models.ManyToManyField(Panel)
    floor = models.ManyToManyField(Floor)
    aisleGroupName = models.CharField(max_length=100)
    total_lights = models.IntegerField(blank=True, null=True)
    one_light_watt = models.IntegerField(blank=True, null=True)
    expected_consumption = models.FloatField(blank=True, null=True)
    cumulative_consumption = models.FloatField(default=0)
    on_sensor_power = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    is_visible = models.BooleanField(default=True)
    visible_date = models.DateField(blank=True, null=True)
    is_this_power_source = models.BooleanField(default=False)
    sources = (
        (0, "MAINS SUPPLY"),
        (1, "DG "),
        (2, "DG 1"),
        (3, "DG 2"),
        (4, "DG 3"),
        (5, "DG 4"),
    )
    power_source = models.PositiveIntegerField(default=0, choices=sources)
    r_phase_pf_threshold = models.FloatField(default=0, blank=True, null=True)
    y_phase_pf_threshold = models.FloatField(default=0, blank=True, null=True)
    b_phase_pf_threshold = models.FloatField(default=0, blank=True, null=True)
    load_graph_color = models.CharField(max_length=30, null=True, blank=True)
    dg_fuel_enabled = models.BooleanField(default=False)
    dg_fuel_provider = models.CharField(
        max_length=32,
        choices=DgFuelProvider.choices,
        null=True,
        blank=True,
    )
    dg_fuel_vehicle_number = models.CharField(max_length=50, null=True, blank=True)
    virtual_siteID = models.ForeignKey(
        to=Site,
        on_delete=models.CASCADE,
        related_name="virtual_site_ID",
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["id", "attached_leg_id"], name="idx_id_leg"),
            models.Index(fields=["site", "attached_leg_id"], name="idx_site_leg"),
            models.Index(fields=["site", "power_source"], name="idx_site_power_source"),
        ]

    def save(self, *args, **kwargs):
        """On first save, sets the virtual site to the aisle's own site when none is given.

        Origin: main (unchanged)
        """
        if self.pk is None and self.virtual_siteID_id is None:
            self.virtual_siteID = self.site
        super().save(*args, **kwargs)

    def __str__(self):
        """Text for this row in admin and logs: self.aisleGroupName + ' ' + str(self.site).

        Origin: main (unchanged)
        """
        return self.aisleGroupName + " " + str(self.site)


def aisle_group_update_leg_id(sender, instance, created=False, **kwargs):
    """A new aisle group's leg id is its own id (set once, on creation).

    Origin: Ashu (changed from main)
    """
    if created and str(instance.attached_leg_id or "") != str(instance.id):
        AisleGroup.objects.filter(id=instance.id).update(attached_leg_id=instance.id)
        instance.attached_leg_id = str(instance.id)


post_save.connect(aisle_group_update_leg_id, sender=AisleGroup)


class AisleInfo(models.Model):
    """Table wareApp_aisleinfo: aisle info. Fields: aisle_name, aisle_group, is_active.

    Origin: Ashu (changed from main)
    """
    aisle_name = models.CharField(max_length=100)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        """Text for this row in admin and logs: self.aisle_name.

        Origin: main (unchanged)
        """
        return self.aisle_name


class SiteBaseline(models.Model):
    """Table wareApp_sitebaseline: site baseline. Fields: associated_site_id, aisle_group, leg_id,
    baseline_value, working_hours, baseline_from, baseline_to.

    Origin: Ashu (changed from main)
    """
    associated_site_id = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    leg_id = models.CharField(max_length=50, null=True, blank=True)
    baseline_value = models.FloatField(default=0)
    working_hours = models.FloatField(default=24)
    baseline_from = models.DateField(blank=True, null=True)
    baseline_to = models.DateField(blank=True, null=True)

    def __str__(self):
        """Text for this row in admin and logs: str(self.baseline_value).

        Origin: main (unchanged)
        """
        return str(self.baseline_value)

    class Meta:
        indexes = [
            models.Index(
                fields=["associated_site_id", "leg_id", "baseline_from", "baseline_to"],
                name="idx_baseline_site_leg_dates",
            )
        ]


class SensorData(models.Model):
    """Table wareApp_sensordata: sensor data. Fields: sensor_id, sensor_associated_with, sensor_status,
    sensor_on_date_time, sensor_off_date_time.

    Origin: main (unchanged)
    """
    sensor_id = models.CharField(max_length=10)
    sensor_associated_with = models.ForeignKey(AisleGroup, on_delete=models.CASCADE)
    sensor_status = models.BooleanField()
    sensor_on_date_time = models.DateTimeField()
    sensor_off_date_time = models.DateTimeField()


class SiteStaticData(models.Model):
    """Table wareApp_sitestaticdata: site static data. Fields: site_id, block_id, aisle_group,
    aisle_id, sensor_id, total_lights, total_watts.

    Origin: main (unchanged)
    """
    site_id = models.ForeignKey(Site, on_delete=models.CASCADE)
    block_id = models.ForeignKey(BlockInfo, on_delete=models.CASCADE)
    aisle_group = models.ForeignKey(AisleGroup, on_delete=models.CASCADE)
    aisle_id = models.ForeignKey(AisleInfo, on_delete=models.CASCADE)
    sensor_id = models.ForeignKey(SensorData, on_delete=models.CASCADE)
    total_lights = models.PositiveIntegerField()
    total_watts = models.CharField(max_length=100)
