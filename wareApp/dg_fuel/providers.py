"""Provider payload parsers for DG-fuel data.

These functions only normalize already-fetched JSON and never issue requests or
write to the database.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .normalization import as_float, epoch_milliseconds


def _items(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list) else []


def _roadcast_telemetry_state(
    status: Any,
    last_update_ms: Optional[int],
    reference_date: Optional[datetime] = None,
) -> str:
    if last_update_ms is None:
        return "UNAVAILABLE"

    last_update_date = datetime.fromtimestamp(last_update_ms / 1000).date()
    compare_date = (
        reference_date.date()
        if isinstance(reference_date, datetime)
        else reference_date
    )
    if compare_date is not None and last_update_date != compare_date:
        return "STALE"

    normalized_status = str(status or "").strip().lower()
    if normalized_status == "online":
        return "CURRENT"
    if normalized_status == "offline":
        return "OFFLINE"
    return "CURRENT"


def extract_roadcast_subscription_expired_errors(
    payload: Any, *, site: Any = None, vehicle_imei: Optional[str] = None
) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    expired_errors = []
    site_candidates = set()
    if site is not None:
        site_id = getattr(site, "id", None)
        site_name = getattr(site, "site_name", None)
        site_imei = getattr(site, "partner_dg_fuel_id", None)
        for candidate in (site_id, site_name, site_imei):
            if candidate is not None and str(candidate).strip():
                site_candidates.add(str(candidate).strip().lower())
    if vehicle_imei:
        site_candidates.add(str(vehicle_imei).strip().lower())

    def _matches_site(item: Dict[str, Any]) -> bool:
        if not site_candidates:
            return True
        values = [
            item.get("deviceId"),
            item.get("device_id"),
            item.get("device_name"),
            item.get("name"),
            item.get("error"),
            item.get("message"),
        ]
        for value in values:
            if value is None:
                continue
            normalized = str(value).strip().lower()
            if not normalized:
                continue
            for candidate in site_candidates:
                if candidate in normalized or normalized in candidate:
                    return True
        return False

    for item in _items(payload.get("error")):
        if not isinstance(item, dict):
            continue
        error_text = str(item.get("error") or "").strip().lower()
        message_text = str(item.get("message") or "").strip().lower()
        if (
            "subscription expired" not in error_text
            and "subscription expired" not in message_text
        ):
            continue
        if not _matches_site(item):
            continue
        expired_errors.append(
            {
                "error": item.get("error"),
                "message": item.get("message"),
                "device_id": item.get("deviceId") or item.get("device_id"),
                "device_name": item.get("name") or item.get("device_name"),
            }
        )
    return expired_errors


def extract_loconav_subscription_expired_errors(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    phrases = (
        "subscription expired",
        "expired subscription",
        "subscription has expired",
    )
    expired_errors: List[Dict[str, Any]] = []

    def _walk(value: Any, field_path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                next_path = f"{field_path}.{key}" if field_path else str(key)
                if isinstance(item, str):
                    normalized_text = item.strip().lower()
                    if any(phrase in normalized_text for phrase in phrases):
                        expired_errors.append(
                            {
                                "field": next_path,
                                "message": item,
                            }
                        )
                elif isinstance(item, (dict, list)):
                    _walk(item, next_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                next_path = f"{field_path}[{index}]" if field_path else f"[{index}]"
                if isinstance(item, str):
                    normalized_text = item.strip().lower()
                    if any(phrase in normalized_text for phrase in phrases):
                        expired_errors.append(
                            {
                                "field": next_path,
                                "message": item,
                            }
                        )
                elif isinstance(item, (dict, list)):
                    _walk(item, next_path)

    _walk(payload)
    return expired_errors


def parse_loconav_current_levels(payload: Any) -> List[Dict[str, Any]]:
    """Normalize LocoNav `current_levels` response rows."""
    if not isinstance(payload, dict):
        return []

    levels = []
    for item in _items(payload.get("data")):
        if not isinstance(item, dict):
            continue
        fuel_liters = as_float(item.get("fuel_in_liters"))
        timestamp_ms = epoch_milliseconds(item.get("timestamp") or item.get("time"))
        vehicle_number = item.get("vehicle_number")
        if fuel_liters is None or timestamp_ms is None or not vehicle_number:
            continue
        levels.append(
            {
                "vehicle_number": str(vehicle_number),
                "fuel_liters": fuel_liters,
                "fuel_capacity": as_float(item.get("fuel_capacity")),
                "percentage": as_float(item.get("value_in_percentage")),
                "epoch_ms": timestamp_ms,
            }
        )
    return levels


def parse_roadcast_current_levels(
    payload: Any,
    allowed_imeis: Optional[Iterable[str]] = None,
    reference_date: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Normalize Roadcast `pull_api` rows into tank-level samples."""
    if not isinstance(payload, dict):
        return []

    allowed = {str(imei) for imei in allowed_imeis} if allowed_imeis else None
    levels = []
    for item in _items(payload.get("data")):
        if not isinstance(item, dict):
            continue
        imei = item.get("deviceImei")
        fuel_liters = as_float(item.get("fuel"))
        timestamp_ms = epoch_milliseconds(item.get("lastUpdate"))
        if not imei or fuel_liters is None or timestamp_ms is None:
            continue
        if allowed is not None and str(imei) not in allowed:
            continue
        telemetry_state = _roadcast_telemetry_state(
            item.get("status"), timestamp_ms, reference_date=reference_date
        )
        levels.append(
            {
                "vehicle_number": str(imei),
                "device_id": item.get("deviceId"),
                "device_name": item.get("name"),
                "device_imei": str(imei),
                "fuel_liters": fuel_liters,
                "last_update": item.get("lastUpdate"),
                "provider_status": item.get("status"),
                "ignition": item.get("ignition"),
                "vehicle_status": item.get("vehicle_status"),
                "device_fix_time": item.get("deviceFixTime"),
                "device_time": item.get("deviceTime"),
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
                "epoch_ms": timestamp_ms,
                "telemetry_state": telemetry_state,
                "is_current_sample": telemetry_state == "CURRENT",
            }
        )
    return levels


def _parallel_events(
    values: Any, timestamps: Any, value_key: str, timestamp_key: str
) -> List[Dict[str, Any]]:
    events = []
    for value, timestamp in zip(_items(values), _items(timestamps)):
        numeric_value = as_float(value)
        timestamp_ms = epoch_milliseconds(timestamp)
        if numeric_value is None or timestamp_ms is None:
            continue
        events.append({value_key: numeric_value, timestamp_key: timestamp_ms})
    return events


def _refill_timestamp_ms(value: Any) -> Optional[int]:
    if isinstance(value, dict):
        for candidate_key in ("end_time", "start_time", "timestamp", "time"):
            timestamp_ms = epoch_milliseconds(value.get(candidate_key))
            if timestamp_ms is not None:
                return timestamp_ms
        return None
    return epoch_milliseconds(value)


def _should_drop_leading_zero_fuel_level(
    fuel_levels: List[Dict[str, Any]],
    *,
    initial_fuel_level: Optional[float],
    fuel_level_at_end: Optional[float],
    fuel_consumed: Optional[float],
) -> bool:
    if not fuel_levels:
        return False

    first_sample = fuel_levels[0]
    first_value = as_float(first_sample.get("fuel_liters"))
    if first_value is None or abs(first_value) > 1e-9:
        return False

    later_positive_sample_exists = any(
        (as_float(sample.get("fuel_liters")) or 0) > 0 for sample in fuel_levels[1:]
    )
    if not later_positive_sample_exists:
        return False

    if initial_fuel_level is not None and initial_fuel_level > 0:
        return True
    if fuel_level_at_end is not None and fuel_level_at_end > 0:
        return True
    if fuel_consumed == 0 and (
        initial_fuel_level is not None or fuel_level_at_end is not None
    ):
        return True
    return False


def parse_roadcast_report(payload: Any) -> Dict[str, Any]:
    """Normalize a Roadcast `pull_fuel_report` response for a DG-run window."""
    if not isinstance(payload, dict):
        return {
            "fuel_consumed": None,
            "fuel_levels": [],
            "refuels": [],
            "thefts": [],
            "fuel_fill_count": 0,
            "fuel_stolen_count": 0,
            "total_fuel_filled": 0,
            "total_fuel_stolen": 0,
        }

    fuel_levels = []
    for item in _items(payload.get("fuel_data")):
        if not isinstance(item, dict):
            continue
        fuel_liters = as_float(item.get("fuel"))
        timestamp_ms = epoch_milliseconds(item.get("time"))
        if fuel_liters is None or timestamp_ms is None:
            continue
        fuel_levels.append({"fuel_liters": fuel_liters, "epoch_ms": timestamp_ms})

    initial_fuel_level = as_float(payload.get("initial_fuel_level"))
    fuel_level_at_end = as_float(payload.get("fuel_level_at_end"))
    fuel_consumed = as_float(payload.get("fuel_consumed"))
    if _should_drop_leading_zero_fuel_level(
        fuel_levels,
        initial_fuel_level=initial_fuel_level,
        fuel_level_at_end=fuel_level_at_end,
        fuel_consumed=fuel_consumed,
    ):
        fuel_levels = fuel_levels[1:]

    fillings = payload.get("fuel_fillings")
    theft_details = payload.get("fuel_stolen_details")
    fillings = fillings if isinstance(fillings, dict) else {}
    theft_details = theft_details if isinstance(theft_details, dict) else {}
    return {
        "device_id": payload.get("device_id"),
        "device_imei": payload.get("device_imei"),
        "device_name": payload.get("device_name"),
        "fuel_consumed": fuel_consumed,
        "initial_fuel_level": initial_fuel_level,
        "fuel_level_at_end": fuel_level_at_end,
        "fuel_levels": fuel_levels,
        "fuel_fill_count": payload.get("fuel_fill_count", 0),
        "fuel_fillings": fillings,
        "refuels": [
            {
                "fuel_liters": as_float(fuel_amount),
                "epoch_ms": timestamp_ms,
            }
            for fuel_amount, timestamp in zip(
                _items(fillings.get("fuel_amounts")),
                _items(fillings.get("refill_time")),
            )
            if as_float(fuel_amount) is not None
            and (timestamp_ms := _refill_timestamp_ms(timestamp)) is not None
        ],
        "fuel_stolen_count": payload.get("fuel_stolen_count", 0),
        "fuel_stolen_details": theft_details,
        "thefts": _parallel_events(
            theft_details.get("stolen_amounts"),
            theft_details.get("theft_time"),
            "fuel_liters",
            "epoch_ms",
        ),
        "total_fuel_filled": as_float(payload.get("total_fuel_filled")),
        "total_fuel_stolen": as_float(payload.get("total_fuel_stolen")),
    }
