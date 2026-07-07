from django.contrib import admin
from django.contrib.admin import ModelAdmin
from .models import *

class HourlyReadingFields(admin.ModelAdmin):

    list_display = ['associated_Site', 'aisle_group', 'unit_consumption', 'reading_from', 'reading_to']

    class Meta:
        model = HourlySiteReading


class SupplyTimeShareFields(admin.ModelAdmin):

    list_display = ['site', 'power_source', 'hourly_run_time', 'reading_from', 'reading_to']

    class Meta:
        model = SupplyLoadTimeShare


class siteLoadPower(admin.ModelAdmin):
    list_display = ['Associated_Site', 'Supply_Source', 'Status']
    readonly_fields = ('Supply_Source', 'Meter_Number')

    class Meta:
        model = SiteLoadPower

class monthlyLoadSharePercentage(admin.ModelAdmin):
    list_display = ['site', 'power_source', 'for_month', 'monthly_time_based_percentage', 'monthly_energy_based_percentage']

    class Meta:
        model = MonthlyLoadSharePercentage


class DailyReadingFields(admin.ModelAdmin):
    list_display = ['associated_Site', 'aisle_group', 'leg_id', 'unit_consumption', 'reading_for']

    class Meta:
        model = DailySiteReading


class SiteBaselineFields(admin.ModelAdmin):
    list_display = ["associated_site_id","aisle_group","leg_id","baseline_value","baseline_from","baseline_to"]

    class Meta:
        model = SiteBaseline


class AisleGroupFields(admin.ModelAdmin):
    list_display = ["site", "aisleGroupName", "attached_leg_id"]

    class Meta:
        model = AisleGroup


class SiteFields(admin.ModelAdmin):
    list_display = ["id", "customer","site_name", "site_type", "location"]

    class Meta:
        model = Site


class FloorFields(admin.ModelAdmin):
    list_display = ["id", "site", "floor"]

    class Meta:
        model = Floor

class EmailHistoryAdmin(admin.ModelAdmin):
    list_display = ["deviceName","fire_site", "email_for"]
    class Meta:
        model = Email_History

class HourlyLoadDataAdmin(admin.ModelAdmin):
    list_display = ["id", "site", "aisle_group", "load_data", "created", "epoch_time", "updated_on"]
    class Meta:
        model = HourlyLoadData

class DailyLoadDataAdmin(admin.ModelAdmin):
    list_display = ["id", "site", "aisle_group", "load_data", "created", "epoch_time", "updated_on"]
    class Meta:
        model = DailyLoadData


class MainsDgLoadDataAdmin(admin.ModelAdmin):
    list_display = ["id", "site", "aisle_group", "load_data", "created", "epoch_time", "updated_on"]
    class Meta:
        model = MainsDgLoadData


class DgFuelConsumptionDataAdmin(admin.ModelAdmin):
    list_display = ["vehicle_number", "fuel_consumption", "epoch_time"]
    class Meta:
        model = DgFuelConsumptionData


class DgUnitConsumptionAdmin(admin.ModelAdmin):
    list_display = ["id", "unit_consumption", "dg_fuel_consumption", "dg_start_date", "dg_end_date", "created", "epoch_time"]
    class Meta:
        model = DgUnitConsumption

class SensorAisleUnitConsumptionAdmin(admin.ModelAdmin):
    list_display = ["leg_id","unit_consumption","reading_for"]
    class Meta:
        model = SensorAisleUnitConsumption

class DGFuelAlertDataAdmin(admin.ModelAdmin):
    list_display = [f.name for f in DGFuelAlertsData._meta.get_fields()]
    class Meta:
        model = DGFuelAlertsData

admin.site.register(User)
admin.site.register(CustomerInfo)
admin.site.register(Site, SiteFields)
admin.site.register(Image)
admin.site.register(BlockInfo)
admin.site.register(AisleInfo)
admin.site.register(HourlySiteReading, HourlyReadingFields)
admin.site.register(AlarmNotifications)
admin.site.register(SiteBaseline, SiteBaselineFields)
admin.site.register(SupplyLoadTimeShare, SupplyTimeShareFields)
admin.site.register(SiteLoadPower, siteLoadPower)
admin.site.register(AisleGroup, AisleGroupFields)
admin.site.register(Panel)
admin.site.register(Floor, FloorFields)
admin.site.register(MeterSource)
admin.site.register(DailySiteReading, DailyReadingFields)
admin.site.register(HomeGatewayId)
admin.site.register(MonthlyLoadSharePercentage, monthlyLoadSharePercentage)
admin.site.register(FirePumpAlarm)
admin.site.register(Email_History,EmailHistoryAdmin)
admin.site.register(FireEquipmentsSystem)
admin.site.register(FireEquipmentsSystemType)
admin.site.register(FansData)
admin.site.register(LightsData)
admin.site.register(RawLoadData)
admin.site.register(HourlyLoadData, HourlyLoadDataAdmin)
admin.site.register(DailyLoadData, DailyLoadDataAdmin)
admin.site.register(MainsDgLoadData, MainsDgLoadDataAdmin)
admin.site.register(PowerFactorData)
admin.site.register(MonthlyMinMaxLoadData)
admin.site.register(DGAlertsData)
admin.site.register(DgFuelConsumptionData)
admin.site.register(DgUnitConsumption, DgUnitConsumptionAdmin)
admin.site.register(DGFuelAlertsData, DGFuelAlertDataAdmin)
admin.site.register(SensorAisleUnitConsumption, SensorAisleUnitConsumptionAdmin)
admin.site.register(CustomerSiteManager)
admin.site.register(SiteLoadParameters)
admin.site.register(NewAlarmsNotifications)
admin.site.register(MeterDisconnectionEvent)
class SiteConsumptionPingAdmin(admin.ModelAdmin):
    list_display = ["site", "home_gateway_id", "is_late_ping", "consumption_ping_time", "updated_on"]
    class Meta:
        model = SiteConsumptionPing

admin.site.register(SiteConsumptionPing, SiteConsumptionPingAdmin)

class SiteCeleryPingAdmin(admin.ModelAdmin):
    list_display = ["site", "home_gateway_id", "leg_id", "aisle_group", "unit_consumption", "celery_ping_time", "updated_on"]
    class Meta:
        model = SiteCeleryPing

admin.site.register(SiteCeleryPing, SiteCeleryPingAdmin)

@admin.register(RecoveryMonitor)
class RecoveryMonitorAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "site",
        "recovery_type",
        "status",
        "leg_id",
        "power_source",
        "expected_slots",
        "recovered_slots",
        "error_slots",
        "requested_at",
        "is_active",
    ]
    list_filter = ["recovery_type", "status", "is_active", "site"]
    search_fields = ["site__site_name", "gateway_id", "leg_id", "failed_reason"]
    readonly_fields = [
        "requested_at",
        "response_received_at",
        "applied_at",
        "verified_at",
    ]
