from django.contrib import admin

from wareApp.mqtt.services.cooldown import release_recovery_request
from .models import (
    AisleGroup,
    AisleInfo,
    AisleSyncRecoveryStatus,
    AlarmNotifications,
    BlockInfo,
    CustomerInfo,
    CustomerSiteManager,
    DGAlertsData,
    DGFuelAlertsData,
    DailyLoadData,
    DailySiteReading,
    DgFuelConsumptionData,
    DgUnitConsumption,
    Email_History,
    FansData,
    FireEquipmentsSystem,
    FireEquipmentsSystemType,
    FirePumpAlarm,
    Floor,
    HomeGatewayId,
    HourlyLoadData,
    HourlySiteReading,
    Image,
    LightsData,
    MainsDgLoadData,
    MeterDisconnectionEvent,
    MeterSource,
    MonthlyLoadSharePercentage,
    MonthlyMinMaxLoadData,
    MqttDeadLetter,
    NewAlarmsNotifications,
    Panel,
    PowerFactorData,
    RawLoadData,
    RecoveryMonitor,
    SensorAisleUnitConsumption,
    Site,
    SiteBaseline,
    SiteCeleryPing,
    SiteConsumptionPing,
    SiteLoadParameters,
    SiteLoadPower,
    SupplyLoadTimeShare,
    User,
)


@admin.register(HourlySiteReading)
class HourlyReadingFields(admin.ModelAdmin):
    list_select_related = ["associated_Site", "aisle_group"]

    list_display = [
        "associated_Site",
        "aisle_group",
        "unit_consumption",
        "reading_from",
        "reading_to",
    ]


@admin.register(SupplyLoadTimeShare)
class SupplyTimeShareFields(admin.ModelAdmin):
    list_select_related = ["site"]

    list_display = [
        "site",
        "power_source",
        "hourly_run_time",
        "reading_from",
        "reading_to",
    ]


@admin.register(SiteLoadPower)
class SiteLoadPowerAdmin(admin.ModelAdmin):
    list_display = ["Associated_Site", "Supply_Source", "Status"]
    readonly_fields = ("Supply_Source", "Meter_Number")


@admin.register(MonthlyLoadSharePercentage)
class MonthlyLoadSharePercentageAdmin(admin.ModelAdmin):
    list_select_related = ["site"]
    list_display = [
        "site",
        "power_source",
        "for_month",
        "monthly_time_based_percentage",
        "monthly_energy_based_percentage",
    ]


@admin.register(DailySiteReading)
class DailyReadingFields(admin.ModelAdmin):
    list_select_related = ["associated_Site", "aisle_group"]
    list_display = [
        "associated_Site",
        "aisle_group",
        "leg_id",
        "unit_consumption",
        "reading_for",
    ]


@admin.register(SiteBaseline)
class SiteBaselineFields(admin.ModelAdmin):
    list_select_related = ["associated_site_id", "aisle_group"]
    list_display = [
        "associated_site_id",
        "aisle_group",
        "leg_id",
        "baseline_value",
        "baseline_from",
        "baseline_to",
    ]


@admin.register(AisleGroup)
class AisleGroupFields(admin.ModelAdmin):
    list_select_related = ["site"]
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


@admin.register(Site)
class SiteFields(admin.ModelAdmin):
    list_select_related = ["customer"]
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


@admin.register(Floor)
class FloorFields(admin.ModelAdmin):
    list_select_related = ["site"]
    list_display = ["id", "site", "floor"]


@admin.register(Email_History)
class EmailHistoryAdmin(admin.ModelAdmin):
    list_display = ["deviceName", "fire_site", "email_for"]


@admin.register(HourlyLoadData)
class HourlyLoadDataAdmin(admin.ModelAdmin):
    list_select_related = ["site", "aisle_group"]
    list_display = [
        "id",
        "site",
        "aisle_group",
        "load_data",
        "created",
        "epoch_time",
        "updated_on",
    ]


@admin.register(DailyLoadData)
class DailyLoadDataAdmin(admin.ModelAdmin):
    list_select_related = ["site", "aisle_group"]
    list_display = [
        "id",
        "site",
        "aisle_group",
        "load_data",
        "created",
        "epoch_time",
        "updated_on",
    ]


@admin.register(MainsDgLoadData)
class MainsDgLoadDataAdmin(admin.ModelAdmin):
    list_select_related = ["site", "aisle_group"]
    list_display = [
        "id",
        "site",
        "aisle_group",
        "load_data",
        "created",
        "epoch_time",
        "updated_on",
    ]


class DgFuelConsumptionDataAdmin(admin.ModelAdmin):
    list_display = ["vehicle_number", "fuel_consumption", "epoch_time"]


@admin.register(DgUnitConsumption)
class DgUnitConsumptionAdmin(admin.ModelAdmin):
    list_select_related = ["aisle_group"]
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


@admin.register(SensorAisleUnitConsumption)
class SensorAisleUnitConsumptionAdmin(admin.ModelAdmin):
    list_display = ["leg_id", "unit_consumption", "reading_for"]


@admin.register(DGFuelAlertsData)
class DGFuelAlertDataAdmin(admin.ModelAdmin):
    list_display = [f.name for f in DGFuelAlertsData._meta.get_fields()]


admin.site.register(User)
admin.site.register(CustomerInfo)
admin.site.register(Image)
admin.site.register(BlockInfo)
admin.site.register(AisleInfo)
admin.site.register(Panel)
admin.site.register(MeterSource)
admin.site.register(HomeGatewayId)
admin.site.register(FirePumpAlarm)
admin.site.register(FireEquipmentsSystem)
admin.site.register(FireEquipmentsSystemType)
admin.site.register(FansData)
admin.site.register(LightsData)
admin.site.register(RawLoadData)
admin.site.register(PowerFactorData)
admin.site.register(MonthlyMinMaxLoadData)
admin.site.register(DGAlertsData)
admin.site.register(DgFuelConsumptionData)
admin.site.register(CustomerSiteManager)
admin.site.register(SiteLoadParameters)
admin.site.register(MeterDisconnectionEvent)


@admin.register(SiteConsumptionPing)
class SiteConsumptionPingAdmin(admin.ModelAdmin):
    list_select_related = ["site"]
    list_display = [
        "site",
        "home_gateway_id",
        "is_late_ping",
        "consumption_ping_time",
        "updated_on",
    ]




@admin.register(SiteCeleryPing)
class SiteCeleryPingAdmin(admin.ModelAdmin):
    list_select_related = ["site"]
    list_display = [
        "site",
        "home_gateway_id",
        "leg_id",
        "aisle_group",
        "unit_consumption",
        "celery_ping_time",
        "updated_on",
    ]




def _retry_recovery(monitors):
    """Re-arm failed/timed-out requests: the next gap packet publishes again."""
    count = 0
    for monitor in monitors:
        monitor.status = "timeout"
        monitor.attempt = 0
        monitor.is_active = True
        monitor.failed_reason = None
        monitor.save(update_fields=["status", "attempt", "is_active", "failed_reason"])
        # Note: with the per-process LocMem cache this clears the cooldown of
        # the web process only; the worker's copy expires after the cooldown
        # (MQTT_RECOVERY_REQUEST_COOLDOWN_SECONDS). A shared Redis cache
        # (REDIS_URL) makes it immediate.
        if monitor.leg_id:
            release_recovery_request(monitor.site_id, "aisle", monitor.leg_id)
        else:
            release_recovery_request(monitor.site_id, "source", monitor.power_source)
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


@admin.register(AlarmNotifications)
class AlarmNotificationsAdmin(admin.ModelAdmin):
    """The single alarm table (consumption, meter, gateway, power and DG)."""

    list_display = [
        "id", "site_id", "Alarm_type", "Alarm_priority", "aisle_group", "power_source",
        "created_time", "last_seen", "occurrences", "is_active",
    ]
    list_filter = ["Alarm_type", "Alarm_priority", "is_active"]
    search_fields = ["site_id__site_name", "to_do", "power_source"]
    list_select_related = ["site_id", "aisle_group"]
    date_hierarchy = "created_time"


@admin.register(NewAlarmsNotifications)
class NewAlarmsNotificationsAdmin(admin.ModelAdmin):
    """Former power / DG alarm table: copied into AlarmNotifications, read-only."""

    list_display = ["id", "site_id", "alarm_type", "power_source", "created"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
