from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.db.models.signals import post_save, pre_save
from django.utils import timezone
from django.db.models import Sum, Q

try:
    from jsonfield import JSONField
except Exception as err:
    print("Error while importing jsonfiled: ", err)


# from model_utils.models import TimeStampedModel
import math

"""
def save(self, *args, **kwargs):
    self.unit_consumption = max(self.unit_consumption, 0)
    self.daily_baseline_value = max(self.daily_baseline_value, 0)
    self.energy_saved = max(self.energy_saved, 0)
    if self.unit_consumption > 10000:
        self.unit_consumption = 0
        self.energy_saved = self.daily_baseline_value
    super(DailySiteReading, self).save(*args, **kwargs)"""


class User(AbstractUser):
    user_type = (
        (1, "Super_Admin"),
        (2, "Aviconn_Admin"),
        (3, "Aviconn_Executive"),
        (4, "Customer"),
        (5, "Cust_Site_Manager"),
    )
    UserType = models.PositiveIntegerField(default=1, choices=user_type)
    Contact_number = models.CharField(
        max_length=15, help_text="Enter the contact number"
    )


def Create_Group(sender, instance, *args, **kwargs):
    if instance._state.adding is True and len(
        Group.objects.filter(name=instance.get_UserType_display())
    ):
        print("Group has been created successfully ")
        Group.objects.create(name=instance.get_UserType_display())


def Add_group_to_user(sender, instance, *args, **kwargs):
    try:
        if instance.UserType == 1:
            User.objects.filter(username=instance.username).update(is_staff=True)
        g = Group.objects.filter(name=instance.get_UserType_display())
        print(g)
        print("Instance has been added inside the group")
        instance.groups.set(g)

    except Exception:
        pass


post_save.connect(Add_group_to_user, sender=User)
pre_save.connect(Create_Group, sender=User)


class CustomerInfo(models.Model):
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

    def __unicode__(self):
        return self.customer.username

    def __str__(self):
        return self.customer.username


class Site(models.Model):
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
    # site_manager = models.ForeignKey(User, related_name='site_manager', on_delete=models.CASCADE, null=True, blank=True)
    site_manager = models.CharField(max_length=50, null=True, blank=True)
    site_manager_contact = models.CharField(max_length=50, null=True, blank=True)
    site_manager_email = models.EmailField(max_length=50, null=True, blank=True)
    avg_saving = models.FloatField(null=True, blank=True)
    max_saving = models.FloatField(null=True, blank=True)
    min_saving = models.FloatField(null=True, blank=True)
    max_threshold_value = models.FloatField(blank=True, null=True)
    min_threshold_value = models.FloatField(blank=True, null=True)
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


class CustomerSiteManager(models.Model):
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
    associated_site = models.ManyToManyField(Site, null=True, blank=True)
    created = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        if self.customer:
            full_name = self.customer.get_full_name().strip()
            return full_name or self.customer.username
        return f"CustomerSiteManager {self.pk}"


class HomeGatewayId(models.Model):
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

    def __unicode__(self):
        return self.hgw_id

    def __str__(self):
        return self.hgw_id


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
    # power_source = models.CharField(max_length=40, blank=True, null=True)
    hourly_run_time = models.IntegerField()
    # total_run_time_till_date = models.IntegerField()
    reading_from = models.DateTimeField(default=timezone.now)
    reading_to = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.get_power_source_display()


class Image(models.Model):
    which_site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    image_file = models.FileField()
    image_id = models.CharField(max_length=10)

    def __str__(self):
        return self.image_file

    def __unicode__(self):
        return self.image_file


class BlockInfo(models.Model):
    block_name = models.CharField(max_length=50)
    site_id = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    is_active = models.BooleanField()

    def __str__(self):
        return self.block_name + " " + str(self.site_id)

    def __unicode__(self):
        return self.block_name + " " + str(self.site_id)


class Panel(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    panel = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return self.panel + " " + str(self.site)

    def __unicode__(self):
        return self.panel + " " + str(self.site)


class Floor(models.Model):
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
        return self.floor + " " + str(self.site)

    def __unicode__(self):
        return self.floor + " " + str(self.site)


class AisleGroup(models.Model):
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
        if self.pk is None and self.virtual_siteID_id is None:
            self.virtual_siteID = self.site
        super().save(*args, **kwargs)

    def __str__(self):
        return self.aisleGroupName + " " + str(self.site)

    def __unicode__(self):
        return self.aisleGroupName + " " + str(self.site)


# class DgFuelSystem(models.Model):
#   aisle_group = models.ForeignKey(AisleGroup, on_delete=models.CASCADE)
#  identifier = models.CharField(max_length=200, null = False, blank=False)


# def __str__(self):
#    return f'{self.aisle_group.aisleGroupName} - {self.identifier}'


def aisle_group_update_leg_id(sender, instance, *args, **kwargs):
    if instance:
        print("new id generated is : ", instance.id)
        leg_id = AisleGroup.objects.filter(id=instance.id).update(
            attached_leg_id=instance.id
        )
        print("leg is successfully update")
        a = AisleGroup.objects.get(id=instance.id).attached_leg_id
        print("leg id is :", a)


post_save.connect(aisle_group_update_leg_id, sender=AisleGroup)


class AisleInfo(models.Model):
    aisle_name = models.CharField(max_length=100)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.aisle_name

    def __unicode__(self):
        return self.aisle_name


class HourlySiteReading(models.Model):
    associated_Site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    leg_id = models.CharField(max_length=50, null=True, blank=True)
    unit_consumption = models.FloatField(default=0)
    hourly_baseline_value = models.FloatField(default=0)
    energy_saved = models.FloatField(default=0)
    reading_from = models.DateTimeField(blank=True, null=True)
    reading_to = models.DateTimeField(blank=True, null=True)
    is_visible = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Sanitize floats — catch NaN, inf, and garbage values
        def clean_float(val, default=0):
            try:
                val = float(val)
                if math.isnan(val) or math.isinf(val):
                    return default
                return max(val, 0)
            except (TypeError, ValueError):
                return default

        # print("actual value: ", self.unit_consumption)
        self.unit_consumption = clean_float(self.unit_consumption)
        self.hourly_baseline_value = clean_float(self.hourly_baseline_value)
        self.energy_saved = clean_float(self.energy_saved)
        # print("clean Value: ", self.unit_consumption)

        if self.unit_consumption > 10000:
            self.unit_consumption = 0
            self.energy_saved = self.hourly_baseline_value

        super(HourlySiteReading, self).save(*args, **kwargs)

    class Meta:
        indexes = [
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


class DailySiteReading(models.Model):
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

    def save(self, *args, **kwargs):
        # Sanitize floats — catch NaN, inf, and garbage values
        def clean_float(val, default=0):
            try:
                val = float(val)
                if math.isnan(val) or math.isinf(val):
                    return default
                return max(val, 0)
            except (TypeError, ValueError):
                return default

        # print("actual value: ", self.unit_consumption)
        self.unit_consumption = clean_float(self.unit_consumption)
        self.daily_baseline_value = clean_float(self.daily_baseline_value)
        self.energy_saved = clean_float(self.energy_saved)
        # print("clean Value: ", self.unit_consumption)

        if self.unit_consumption > 10000:
            self.unit_consumption = 0
            self.energy_saved = self.daily_baseline_value

        super(DailySiteReading, self).save(*args, **kwargs)

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


class SiteBaseline(models.Model):
    associated_site_id = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True
    )
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    leg_id = models.CharField(max_length=50, null=True, blank=True)
    baseline_value = models.FloatField(default=0)
    working_hours = models.FloatField(default=24)
    # created = models.DateTimeField(auto_now=True)
    baseline_from = models.DateField(blank=True, null=True)
    baseline_to = models.DateField(blank=True, null=True)

    def __str__(self):
        return str(self.baseline_value)


# class AlarmNotifications(models.Model):
#     created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
#     site_id = models.ForeignKey(Site, on_delete=models.CASCADE)
#     USER_LEVEL = ((1, 'Super_Admin'), (2, 'Aviconn_Admin'), (3, 'Aviconn_Executive'), (4, "Customer"),
#                   (5, 'Cust_Site_Manager'))
#     user_level = models.PositiveIntegerField(choices=USER_LEVEL, default=1)
#     OBJECT_TYPE = ((0, 'No_Type'), (1, 'Sensor'), (3, 'Light'), (4, 'Meter'), (5, 'Gateway'))
#     object_type = models.PositiveIntegerField(default=0, choices=OBJECT_TYPE)
#     object_id = models.PositiveIntegerField(blank=True, null=True)
#     alarm_type = ((0, "Low_balance"), (1, "Power_Cut"), (2, "Pending Balance"), (3, "Pending Request"),
#                   (4, "Zero balance"), (5, "Box opened"), (6, "Internet_Gone"), (7, "No meter reading"))
#     Alarm_type = models.PositiveIntegerField(choices=alarm_type)
#     create_DateTime = models.DateTimeField(auto_now=False, auto_now_add=True)
#     alarm_priorities = ((0, 'Normal'), (1, 'High'))
#     Alarm_priority = models.PositiveIntegerField(choices=alarm_priorities, default=0)
#     created_time = models.DateTimeField(default=timezone.now)
#     to_do = models.CharField(max_length=200, blank=True, null=True)
#     off_time = models.DateTimeField(default=timezone.now)
#     cloud_time = models.DateTimeField(auto_now=False, auto_now_add=True)
#     is_active = models.BooleanField(default=True)

#     def __unicode__(self):
#         return "Notification for {}".format(str(self.site_id))

#     def __str__(self):
#         return "Notification for {}".format(str(self.site_id))


class AlarmNotifications(models.Model):
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
    alarm_type = (
        (0, "Low_balance"),
        (1, "Power_Cut"),
        (2, "Pending Balance"),
        (3, "Pending Request"),
        (4, "Zero balance"),
        (5, "Box opened"),
        (6, "Internet_Gone"),
        (7, "High Consumption"),
        (8, "Low Consumption"),
        (9, "No DG Run"),
    )
    Alarm_type = models.PositiveIntegerField(choices=alarm_type)
    create_DateTime = models.DateTimeField(auto_now=False, auto_now_add=True)
    alarm_priorities = ((0, "Normal"), (1, "High"))
    Alarm_priority = models.PositiveIntegerField(choices=alarm_priorities, default=0)
    created_time = models.DateTimeField(default=timezone.now)
    to_do = models.CharField(max_length=200, blank=True, null=True)
    off_time = models.DateTimeField(default=timezone.now)
    cloud_time = models.DateTimeField(auto_now=False, auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __unicode__(self):
        return "Notification for {}".format(str(self.site_id))

    def __str__(self):
        return "Notification for {}".format(str(self.site_id))


class SensorData(models.Model):
    sensor_id = models.CharField(max_length=10)
    sensor_associated_with = models.ForeignKey(AisleGroup, on_delete=models.CASCADE)
    sensor_status = models.BooleanField()
    sensor_on_date_time = models.DateTimeField()
    sensor_off_date_time = models.DateTimeField()


class SiteStaticData(models.Model):
    site_id = models.ForeignKey(Site, on_delete=models.CASCADE)
    block_id = models.ForeignKey(BlockInfo, on_delete=models.CASCADE)
    aisle_group = models.ForeignKey(AisleGroup, on_delete=models.CASCADE)
    aisle_id = models.ForeignKey(AisleInfo, on_delete=models.CASCADE)
    sensor_id = models.ForeignKey(SensorData, on_delete=models.CASCADE)
    total_lights = models.PositiveIntegerField()
    total_watts = models.CharField(max_length=100)


class OTP(models.Model):
    otp = models.CharField(blank=True, null=True, max_length=5)
    user_id = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now=False, auto_now_add=True)

    def __unicode__(self):
        return "OTP  {} on {}".format(self.otp, self.created)

    def __str__(self):
        return "OTP  {} on {}".format(self.otp, self.created)


class SiteLoadPower(models.Model):
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
        ]

    def __str__(self):
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

    def __unicode__(self):
        return (
            "Total Load: {},R-phase voltage: {}, Y-phase voltage: {}, B-phase voltage: {},"
            " R-phase current: {},"
            " Y-phase current: {}, B-phase current: {}".format(
                str(self.Site_Total_Load),
                str(self.r_volt),
                str(self.y_volt),
                str(self.b_volt),
                str(self.r_current),
                str(self.y_current),
                str(self.b_current),
            )
        )


class MeterSource(models.Model):
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
        return str(self.power_source_1)

    def __unicode__(self):
        return str(self.power_source_1)


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

    def __unicode__(self):
        return self.reading_of

    def __str__(self):
        return self.reading_of


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


class FireEquipmentsSystemType(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    devicename = models.CharField(max_length=30, null=True, blank=True)
    categories = models.CharField(max_length=30, null=True, blank=True)

    def __str__(self):
        return self.devicename


class FireEquipmentsSystem(models.Model):
    deviceType = models.ForeignKey(
        FireEquipmentsSystemType, on_delete=models.CASCADE, null=True, blank=True
    )
    assetNo = models.CharField(max_length=20, null=True, blank=True)
    modelNo = models.CharField(max_length=30, null=True, blank=True)
    loaction = models.CharField(max_length=30, null=True, blank=True)
    Warrenty_till = models.DateField(blank=True, null=True)
    last_service = models.DateField(blank=True, null=True)
    next_service = models.DateField(blank=True, null=True)
    updatedBy = models.CharField(max_length=25, blank=True, null=True)

    def __str__(self):
        return self.modelNo


class LightsData(models.Model):
    areaName = models.CharField(max_length=40, null=True, blank=True)
    totalLights = models.IntegerField(null=True, blank=True)
    watt_18_Lights = models.IntegerField(null=True, blank=True)
    watt_20_Lights = models.IntegerField(null=True, blank=True)
    watt_24_Lights = models.IntegerField(null=True, blank=True)
    watt_36_Lights = models.IntegerField(null=True, blank=True)
    watt_40_Lights = models.IntegerField(null=True, blank=True)
    totalWattLights = models.IntegerField(null=True, blank=True)
    totalUnits = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.areaName


class FansData(models.Model):
    areaName = models.CharField(max_length=40, null=True, blank=True)
    totalFans = models.IntegerField(null=True, blank=True)
    watt_80_Lights = models.IntegerField(null=True, blank=True)
    watt_100_Lights = models.IntegerField(null=True, blank=True)
    totalWattFans = models.IntegerField(null=True, blank=True)
    totalUnits = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.areaName


class RawLoadData(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    load_data = models.FloatField(blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    epoch_time = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return str(self.load_data)


class HourlyLoadData(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    load_data = models.FloatField(blank=True, null=True)
    epoch_time = models.CharField(max_length=50, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated_on = models.DateTimeField(auto_now=datetime.now())
    is_bypassed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["site", "created"], name="idx_load_site_created"),
            models.Index(
                fields=["aisle_group", "created"], name="idx_load_aislegroup_created"
            ),
        ]

    def __str__(self):
        return str(self.load_data)


class DailyLoadData(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    load_data = models.FloatField(blank=True, null=True)
    epoch_time = models.CharField(max_length=50, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated_on = models.DateTimeField(auto_now=datetime.now())

    def __str__(self):
        return str(self.load_data)


class MainsDgLoadData(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    aisle_group = models.ForeignKey(
        AisleGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    load_data = models.FloatField(blank=True, null=True)
    epoch_time = models.CharField(max_length=200, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated_on = models.DateTimeField(auto_now=datetime.now())

    def __str__(self):
        return str(self.load_data)


class PowerFactorData(models.Model):
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
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    supply_source = models.CharField(max_length=20, null=True, blank=True)
    min_load = models.FloatField(default=0, blank=True, null=True)
    min_load_created = models.DateTimeField(blank=True, null=True)
    max_load = models.FloatField(default=0, blank=True, null=True)
    max_load_created = models.DateTimeField(blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.supply_source


class DGAlertsData(models.Model):
    alert_data = JSONField(default=dict)
    created = models.DateTimeField(auto_now=datetime.now())
    # created_at = models.DateTimeField(null = True)

    def __str__(self):
        return str(self.alert_data)


class DgFuelConsumptionData(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    vehicle_number = models.CharField(max_length=50, null=True, blank=True, default=1)
    # vehicle_number = models.ForeignKey(DgFuelSystem, on_delete=models.CASCADE, null=True, blank=True)
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
        return self.vehicle_number


class DgUnitConsumption(models.Model):
    class DailyDataStatus(models.TextChoices):
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
    updated_on = models.DateTimeField(auto_now=datetime.now())
    epoch_time = models.CharField(max_length=50, null=True, blank=True)
    is_dg_on = models.BooleanField(default=False)
    fetch_fuel_data = models.BooleanField(default=False)
    daily_data_status = models.CharField(
        max_length=16,
        choices=DailyDataStatus.choices,
        default=DailyDataStatus.COMPLETED,
    )
    daily_data_retry_count = models.PositiveIntegerField(default=0)
    daily_data_last_attempt_at = models.DateTimeField(null=True, blank=True)
    daily_data_retry_deadline = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return str(self.unit_consumption)

class DGFuelAlertsData(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    alert_name = models.CharField(max_length=50, null=True, blank=True)
    vehicle_number = models.CharField(max_length=50, null=True, blank=True)
    fuel_consumption = models.FloatField(default=0, null=True, blank=True)
    epoch_time = models.CharField(max_length=50, null=True, blank=True)
    created = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.alert_name

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "vehicle_number", "alert_name", "epoch_time"],
                name="uniq_dgfuel_alert_site_vehicle_name_epoch",
            )
        ]


class NewAlarmsNotifications(models.Model):
    site_id = models.ForeignKey(Site, on_delete=models.CASCADE)
    ALARM_TYPE = (
        (0, "High Voltage"),
        (1, "Low Voltage"),
        (2, "PF Bad Value Alarm"),
        (3, "DG Overtime"),
        (4, "DG Fuel Under Level"),
        (5, "Mains Higher Consumption"),
        (6, "Fuel Drain"),
    )
    alarm_type = models.PositiveIntegerField(choices=ALARM_TYPE, blank=True, null=True)
    ALARM_PRIORITY = ((0, "High"), (1, "Medium"), (2, "Low"))
    alarm_priority = models.PositiveIntegerField(
        choices=ALARM_PRIORITY, blank=True, null=True
    )
    power_source = models.CharField(max_length=50, blank=True, null=True)
    r_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    y_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    b_phase = models.DecimalField(decimal_places=2, max_digits=6, blank=True, null=True)
    fuel_level = models.FloatField(blank=True, null=True)
    run_hours = models.FloatField(blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    off_time = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __unicode__(self):
        return "Notification for {}".format(str(self.site_id))

    def save(self, *args, **kwargs):
        def _safe_round(val):
            try:
                if val is None:
                    return None
                return round(float(val), 2)
            except Exception:
                return None

        self.r_phase = _safe_round(self.r_phase)
        self.y_phase = _safe_round(self.y_phase)
        self.b_phase = _safe_round(self.b_phase)
        super(NewAlarmsNotifications, self).save(*args, **kwargs)

    def __str__(self):
        return "Notification for {}".format(str(self.site_id))


class SiteLoadParameters(models.Model):
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

    def __unicode__(self):
        return "Notification for {}".format(str(self.site_id))

    def save(self, *args, **kwargs):
        self.r_phase = round(float(self.r_phase), 2)
        self.y_phase = round(float(self.y_phase), 2)
        self.b_phase = round(float(self.b_phase), 2)
        super(SiteLoadParameters, self).save(*args, **kwargs)

    def __str__(self):
        return "Notification for {}".format(str(self.site_id))


class SiteConsumptionPing(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    home_gateway_id = models.CharField(max_length=200, blank=True, null=True)
    is_late_ping = models.BooleanField(default=False, verbose_name="Late Ping Flag")
    consumption_ping_time = models.DateTimeField(
        blank=True, null=True, verbose_name="Time of Consumption Ping"
    )
    updated_on = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.site.site_name if self.site else 'Unknown'} - {self.consumption_ping_time}"


class SiteCeleryPing(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    home_gateway_id = models.CharField(max_length=200, blank=True, null=True)
    leg_id = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Leg ID"
    )
    aisle_group = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Aisle Group"
    )
    unit_consumption = models.FloatField(
        blank=True, null=True, verbose_name="Unit Consumption"
    )
    celery_ping_time = models.DateTimeField(
        blank=True, null=True, verbose_name="Time of Celery Ping"
    )
    updated_on = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.site.site_name if self.site else 'Unknown'} - {self.celery_ping_time}"


class RecoveryMonitor(models.Model):
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

    class Meta:
        indexes = [
            models.Index(
                fields=["site", "recovery_type", "status"],
                name="idx_recovery_site_status",
            ),
            models.Index(
                fields=["site", "leg_id", "recovery_type"], name="idx_recovery_site_leg"
            ),
            models.Index(
                fields=["site", "power_source", "recovery_type"],
                name="idx_recovery_site_source",
            ),
            models.Index(
                fields=["requested_at", "is_active"], name="idx_recovery_active_time"
            ),
        ]
        ordering = ["-requested_at"]

    def __str__(self):
        return "{} {} {}".format(self.site, self.recovery_type, self.status)


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
