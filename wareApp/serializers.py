import base64
import binascii

from django.contrib.auth import authenticate
from rest_framework import serializers

from .models import AlarmNotifications, CustomerInfo, MeterDisconnectionEvent, Site, User

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()

    
    def validate(self, data):
        # The client sends the password base64-encoded. Never log or print it.
        username = data.get("username", "")
        try:
            password = base64.b64decode(data.get("password", ""), validate=True)
        except (binascii.Error, ValueError):
            raise serializers.ValidationError("invalid data")

        if not username or not password:
            raise serializers.ValidationError("invalid data")
        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError("invalid credentials. try again")
        data["user"] = user
        return data


# for login purpose
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "UserType", "first_name", "last_name", "Contact_number"]


class UserCustomerInfoSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ["id", "username", "email", "Contact_number", "first_name", "last_name"]


class CustomerInfoSerializer(serializers.ModelSerializer):

    customer = UserCustomerInfoSerializer(many=False, read_only=True)

    class Meta:
        model = CustomerInfo
        fields = ["address", "total_sites", "customer"]


class SiteSerializer(serializers.ModelSerializer):

    #site_manager = UserSerializer(many=False, read_only=True)

    class Meta:
        model = Site
        fields = ["site_name",
                "is_pf_visible",
                  "is_loadGraph_visible",
                  "show_dg_mains_run_time",
                  "total_no_of_blocks",
                  "total_no_of_aisles",
                  "location",
                  "no_of_single_source_meters",
                  "no_of_dual_source_meters",
                  "site_manager",
                  "site_type",
                  "dg_fuel_system_installed",
                  "customer_visible_dg_fuel_data",
                  "site_manager_contact",
                  "site_manager_email",
                  "is_carbon_emission_visible",
                  "is_hourly_data_visible_customer",
                  "is_alarm_History_active",
                  "id",
                  "live_date"]

class AlarmListSerializer(serializers.ModelSerializer):
    """One alarm row for the site alarm detail list.

    Keeps the keys of the former NewAlarmsNotifications list (the dashboard reads
    them) and adds the aisle, reason and repeat count of the single alarm table.
    """

    get_alarm_type_display = serializers.CharField(source="get_Alarm_type_display", read_only=True)
    get_alarm_priority_display = serializers.CharField(source="get_Alarm_priority_display", read_only=True)
    created = serializers.DateTimeField(source="created_time", read_only=True)
    aisle_group = serializers.CharField(source="aisle_group.aisleGroupName", default=None, read_only=True)
    issue = serializers.CharField(source="to_do", default=None, read_only=True)

    class Meta:
        model = AlarmNotifications
        fields = [
            "get_alarm_type_display", "power_source", "get_alarm_priority_display",
            "r_phase", "y_phase", "b_phase", "fuel_level", "run_hours", "created",
            "is_active", "aisle_group", "issue", "occurrences", "last_seen",
        ]

class MeterDisconnectionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeterDisconnectionEvent
        fields = [
            "id",
            "logged_site_id",
            "meter_id",
            "meter_number",
            "meter_name",
            "status",
            "port_id",
            "detection_window_start",
            "detection_window_end",
            "last_seen_at",
            "source_log_path",
            "raw_log_line",
            "synced_to_cloud",
            "synced_at",
            "cloud_response",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

