from django.contrib import admin
from django.contrib.admin import ModelAdmin
from .models import *


class HourlyReadingFields(admin.ModelAdmin):

    list_display = [
        "associated_Site",
        "aisle_group",
        "unit_consumption",
        "reading_from",
        "reading_to",
    ]

    class Meta:
        model = HourlySiteReading


class SupplyTimeShareFields(admin.ModelAdmin):

    list_display = [
        "site",
        "power_source",
        "hourly_run_time",
        "reading_from",
        "reading_to",
    ]

    class Meta:
        model = SupplyLoadTimeShare


class siteLoadPower(admin.ModelAdmin):
    list_display = ["Associated_Site", "Supply_Source", "Status"]
    readonly_fields = ("Supply_Source", "Meter_Number")

    class Meta:
        model = SiteLoadPower


class monthlyLoadSharePercentage(admin.ModelAdmin):
    list_display = [
        "site",
        "power_source",
        "for_month",
        "monthly_time_based_percentage",
        "monthly_energy_based_percentage",
    ]

    class Meta:
        model = MonthlyLoadSharePercentage


class DailyReadingFields(admin.ModelAdmin):
    list_display = [
        "associated_Site",
        "aisle_group",
        "leg_id",
        "unit_consumption",
        "reading_for",
    ]

    class Meta:
        model = DailySiteReading


class SiteBaselineFields(admin.ModelAdmin):
    list_display = [
        "associated_site_id",
        "aisle_group",
        "leg_id",
        "baseline_value",
        "baseline_from",
        "baseline_to",
    ]

    class Meta:
        model = SiteBaseline


class AisleGroupFields(admin.ModelAdmin):
    list_display = [
        "site",
        "aisleGroupName",
        "attached_leg_id",
        "power_source",
        "dg_fuel_enabled",
        "dg_fuel_provider",
        "dg_fuel_vehicle_number",
    ]
    list_filter = ["power_source", "dg_fuel_enabled", "dg_fuel_provider"]
    search_fields = ["site__site_name", "aisleGroupName", "attached_leg_id"]

    class Meta:
        model = AisleGroup


class SiteFields(admin.ModelAdmin):
    list_display = [
        "id",
        "customer",
        "site_name",
        "site_type",
        "location",
        "nl_operation_hours",
        "high_consumption_units",
        "bypass_consumption_units",
    ]

    class Meta:
        model = Site


class FloorFields(admin.ModelAdmin):
    list_display = ["id", "site", "floor"]

    class Meta:
        model = Floor


class EmailHistoryAdmin(admin.ModelAdmin):
    list_display = ["deviceName", "fire_site", "email_for"]

    class Meta:
        model = Email_History


class HourlyLoadDataAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "site",
        "aisle_group",
        "load_data",
        "created",
        "epoch_time",
        "updated_on",
    ]

    class Meta:
        model = HourlyLoadData


class DailyLoadDataAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "site",
        "aisle_group",
        "load_data",
        "created",
        "epoch_time",
        "updated_on",
    ]

    class Meta:
        model = DailyLoadData


class MainsDgLoadDataAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "site",
        "aisle_group",
        "load_data",
        "created",
        "epoch_time",
        "updated_on",
    ]

    class Meta:
        model = MainsDgLoadData


class DgFuelConsumptionDataAdmin(admin.ModelAdmin):
    list_display = ["vehicle_number", "fuel_consumption", "epoch_time"]

    class Meta:
        model = DgFuelConsumptionData


class DgUnitConsumptionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "aisle_group",
        "unit_consumption",
        "dg_fuel_consumption",
        "fuel_provider",
        "fuel_vehicle_number",
        "dg_start_date",
        "dg_end_date",
        "created",
        "epoch_time",
    ]

    class Meta:
        model = DgUnitConsumption


class SensorAisleUnitConsumptionAdmin(admin.ModelAdmin):
    list_display = ["leg_id", "unit_consumption", "reading_for"]

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
admin.site.register(Email_History, EmailHistoryAdmin)
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
    list_display = [
        "site",
        "home_gateway_id",
        "is_late_ping",
        "consumption_ping_time",
        "updated_on",
    ]

    class Meta:
        model = SiteConsumptionPing


admin.site.register(SiteConsumptionPing, SiteConsumptionPingAdmin)


class SiteCeleryPingAdmin(admin.ModelAdmin):
    list_display = [
        "site",
        "home_gateway_id",
        "leg_id",
        "aisle_group",
        "unit_consumption",
        "celery_ping_time",
        "updated_on",
    ]

    class Meta:
        model = SiteCeleryPing


admin.site.register(SiteCeleryPing, SiteCeleryPingAdmin)


def _retry_recovery(monitors):
    """Re-arm failed/timed-out requests: the next gap packet publishes again."""
    from django.core.cache import cache

    count = 0
    for monitor in monitors:
        monitor.status = "timeout"
        monitor.attempt = 0
        monitor.is_active = True
        monitor.failed_reason = None
        monitor.save(update_fields=["status", "attempt", "is_active", "failed_reason"])
        scope = (
            f"aisle:{monitor.leg_id}"
            if monitor.leg_id
            else f"source:{monitor.power_source}"
        )
        cache.delete(f"mqtt:recovery-req:{monitor.site_id}:{scope}")
        AisleSyncRecoveryStatus.objects.filter(recovery_monitor=monitor).update(
            sync_status="missing", last_error=None
        )
        count += 1
    return count


@admin.register(AisleSyncRecoveryStatus)
class AisleSyncRecoveryStatusAdmin(admin.ModelAdmin):
    list_display = [
        "site",
        "home_gateway_id",
        "aisle_group",
        "power_source",
        "leg_id",
        "sync_status",
        "is_sync_gone",
        "has_data_loss",
        "missing_slots",
        "recovered_slots",
        "last_sync_at",
        "updated_at",
    ]
    list_filter = ["sync_status", "is_sync_gone", "has_data_loss", "site"]
    search_fields = ["site__site_name", "home_gateway_id", "leg_id"]
    actions = ["retry_failed_recovery"]

    @admin.action(description="Retry recovery for selected (failed) rows")
    def retry_failed_recovery(self, request, queryset):
        monitors = RecoveryMonitor.objects.filter(
            id__in=queryset.exclude(recovery_monitor__isnull=True).values(
                "recovery_monitor_id"
            ),
            status__in=("failed", "timeout"),
        )
        self.message_user(request, f"{_retry_recovery(monitors)} request(s) re-armed.")


@admin.register(RecoveryMonitor)
class RecoveryMonitorAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "site",
        "recovery_type",
        "status",
        "attempt",
        "leg_id",
        "power_source",
        "missing_from",
        "missing_to",
        "expected_slots",
        "recovered_slots",
        "error_slots",
        "catch_up_at",
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
        "catch_up_at",
    ]
    actions = ["retry_recovery"]

    @admin.action(description="Retry selected failed / timed-out requests")
    def retry_recovery(self, request, queryset):
        count = _retry_recovery(queryset.filter(status__in=("failed", "timeout")))
        self.message_user(request, f"{count} request(s) re-armed.")


@admin.register(MqttDeadLetter)
class MqttDeadLetterAdmin(admin.ModelAdmin):
    list_display = ["id", "message_type", "site_id", "gateway_id", "created_at", "is_resolved"]
    list_filter = ["message_type", "is_resolved"]
    search_fields = ["gateway_id", "error", "payload"]
    readonly_fields = ["message_type", "site_id", "gateway_id", "payload", "error", "created_at"]
