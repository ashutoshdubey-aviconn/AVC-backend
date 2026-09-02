"""Provider payload parsers for DG-fuel data.

These functions only normalize already-fetched JSON and never issue requests or
write to the database.
"""

from typing import Any, Dict, Iterable, List, Optional

from .normalization import as_float, epoch_milliseconds


def _items(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list) else []


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
    payload: Any, allowed_imeis: Optional[Iterable[str]] = None
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
        levels.append(
            {
                "vehicle_number": str(imei),
                "fuel_liters": fuel_liters,
                "epoch_ms": timestamp_ms,
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


def parse_roadcast_report(payload: Any) -> Dict[str, Any]:
    """Normalize a Roadcast `pull_fuel_report` response for a DG-run window."""
    if not isinstance(payload, dict):
        return {"fuel_consumed": None, "fuel_levels": [], "refuels": [], "thefts": []}

    fuel_levels = []
    for item in _items(payload.get("fuel_data")):
        if not isinstance(item, dict):
            continue
        fuel_liters = as_float(item.get("fuel"))
        timestamp_ms = epoch_milliseconds(item.get("time"))
        if fuel_liters is None or timestamp_ms is None:
            continue
        fuel_levels.append({"fuel_liters": fuel_liters, "epoch_ms": timestamp_ms})

    fillings = payload.get("fuel_fillings")
    theft_details = payload.get("fuel_stolen_details")
    fillings = fillings if isinstance(fillings, dict) else {}
    theft_details = theft_details if isinstance(theft_details, dict) else {}
    return {
        "fuel_consumed": as_float(payload.get("fuel_consumed")),
        "initial_fuel_level": as_float(payload.get("initial_fuel_level")),
        "fuel_level_at_end": as_float(payload.get("fuel_level_at_end")),
        "fuel_levels": fuel_levels,
        "refuels": _parallel_events(
            fillings.get("fuel_amounts"),
            fillings.get("refill_time"),
            "fuel_liters",
            "epoch_ms",
        ),
        "thefts": _parallel_events(
            theft_details.get("stolen_amounts"),
            theft_details.get("theft_time"),
            "fuel_liters",
            "epoch_ms",
        ),
    }