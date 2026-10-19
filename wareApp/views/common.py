"""Shared helpers: DG-fuel database alias and the fuel-provider imports."""

import re
from datetime import datetime

from django.conf import settings

try:
    from wareApp.dg_fuel.normalization import epoch_milliseconds
    from wareApp.dg_fuel.providers import (
        extract_loconav_subscription_expired_errors,
        extract_roadcast_subscription_expired_errors,
    )
    from wareApp.fuel_providers import fetch_loconav_report, fetch_roadcast_pull_api
except ImportError:

    def epoch_milliseconds(value):
        if value is None or isinstance(value, bool):
            return None

        try:
            numeric_value = int(float(str(value).strip()))
        except (TypeError, ValueError):
            numeric_value = None

        if numeric_value is not None:
            return (
                numeric_value
                if numeric_value >= 1000000000000
                else numeric_value * 1000
            )

        try:
            normalized_value = str(value).strip().replace("Z", "+00:00")
            normalized_value = re.sub(
                r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized_value
            )
            parsed = datetime.fromisoformat(normalized_value)
        except (TypeError, ValueError):
            return None

        return int(parsed.timestamp() * 1000)

    def extract_loconav_subscription_expired_errors(payload):
        return []

    def extract_roadcast_subscription_expired_errors(
        payload, *, site=None, vehicle_imei=None
    ):
        return []

    def fetch_loconav_report(*args, **kwargs):
        return {}

    def fetch_roadcast_pull_api(*args, **kwargs):
        return {}


DG_FUEL_DB_ALIAS = "secondary"


def _dg_fuel_db_alias():
    databases = getattr(settings, "DATABASES", {})
    return DG_FUEL_DB_ALIAS if DG_FUEL_DB_ALIAS in databases else "default"


def _dg_fuel_queryset(model_manager):
    return model_manager.using(_dg_fuel_db_alias())
