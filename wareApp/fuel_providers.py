import time
import requests
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from wareApp.dg_fuel.providers import parse_roadcast_report

LOG = logging.getLogger(__name__)


def _try_request(
    url: str,
    params: dict = None,
    headers: dict = None,
    timeout: int = 8,
    retries: int = 3,
    backoff: float = 0.5,
):
    attempt = 0
    while attempt < retries:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            return r
        except Exception as exc:
            attempt += 1
            if attempt >= retries:
                LOG.debug("_try_request: final failure for %s: %s", url, exc)
                return None
            time.sleep(backoff)
            backoff *= 2
    return None


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        try:
            return float(str(value).strip())
        except Exception:
            return None


def fetch_roadcast_fuel(
    vehicle_imei: str, start_dt: datetime, end_dt: datetime
) -> Optional[float]:
    """Robustly fetch fuel_consumed from Roadcaste endpoints.
    Returns numeric value or None on failure.
    """
    url = "https://test-track.roadcast.net/api/v1/auth/pull_fuel_report"
    headers = {"Authorization": "Basic QXZpY29ubjpBYmNAMTIzNA=="}
    params = {
        "device_imei": vehicle_imei,
        "from_time": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "to_time": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # try primary endpoint (few attempts)
    r = _try_request(url, params=params, headers=headers, retries=2, timeout=8)
    if r is not None and r.status_code == 200:
        try:
            j = r.json()
            v = j.get("fuel_consumed") if isinstance(j, dict) else None
            fv = _to_float(v)
            if fv is not None:
                return fv
        except Exception:
            LOG.debug(
                "fetch_roadcast_fuel: could not parse primary JSON for %s", vehicle_imei
            )

    # mapping fallback: try to map imei/deviceId to canonical device and retry once
    try:
        map_url = "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234"
        m = _try_request(map_url, timeout=8, retries=2)
        if m is not None and m.status_code == 200:
            mj = m.json()
            for dev in mj.get("data", []) if isinstance(mj, dict) else []:
                if str(dev.get("deviceImei")) == str(vehicle_imei) or str(
                    dev.get("deviceId")
                ) == str(vehicle_imei):
                    mapped = dev.get("deviceImei")
                    if mapped:
                        params["device_imei"] = mapped
                        r2 = _try_request(
                            url, params=params, headers=headers, retries=2, timeout=8
                        )
                        if r2 is not None and r2.status_code == 200:
                            try:
                                j2 = r2.json()
                                v2 = (
                                    j2.get("fuel_consumed")
                                    if isinstance(j2, dict)
                                    else None
                                )
                                fv2 = _to_float(v2)
                                if fv2 is not None:
                                    return fv2
                            except Exception:
                                LOG.debug(
                                    "fetch_roadcast_fuel: parse failure on mapped imei %s",
                                    mapped,
                                )
    except Exception:
        LOG.debug("fetch_roadcast_fuel: mapping fallback failed for %s", vehicle_imei)

    return None


def fetch_roadcast_pull_api() -> Optional[Dict[str, Any]]:
    url = "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api"
    params = {"username": "Aviconn", "password": "Abc@1234"}
    response = _try_request(url, params=params, timeout=8, retries=2)
    if response is None or response.status_code != 200:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def vehicle_variants(v: str) -> List[str]:
    if not v:
        return []
    v = str(v).strip()
    variants = [v]
    try:
        variants.append(v.upper())
        variants.append(v.lower())
        variants.append(v.replace(" ", ""))
        alnum = "".join(ch for ch in v if ch.isalnum())
        if alnum not in variants:
            variants.append(alnum)
    except Exception:
        pass
    # dedupe preserving order
    seen = set()
    out = []
    for x in variants:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def fetch_loconav_fuel(
    vehicle_number: str, start_dt: datetime, end_dt: datetime
) -> Optional[float]:
    """Attempt to fetch Loconav fuel consumed between start_dt and end_dt.
    Returns numeric fuel_consumed or None.
    """
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    # First try the consolidated fuel endpoint which returns total consumption
    for v in [vehicle_number]:
        url = f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={v}&start_time={start_ts}&end_time={end_ts}"
        r = _try_request(url, headers=headers, timeout=8, retries=2)
        if r is None:
            continue
        try:
            j = r.json()
        except Exception:
            continue
        if isinstance(j, dict) and "data" in j:
            data = j["data"]
            # if API returns a wrapper with fuel_consumption
            if isinstance(data, dict) and "fuel_consumption" in data:
                fc = data.get("fuel_consumption")
                if isinstance(fc, dict):
                    val = _to_float(
                        fc.get("value")
                        or fc.get("fuel_in_liters")
                        or fc.get("consumed")
                    )
                    if val is not None:
                        return val
            # if API returns 'data' list with 'fuel_consumption' present, try sum
            if isinstance(data, list) and data:
                # attempt to find aggregated value
                for item in data:
                    if isinstance(item, dict) and "fuel_consumption" in item:
                        fc = item.get("fuel_consumption")
                        if isinstance(fc, dict):
                            vval = _to_float(
                                fc.get("value") or fc.get("fuel_in_liters")
                            )
                            if vval is not None:
                                return vval

    # Fallback: use interval_data to estimate consumption as initial - final (non-negative)
    for v in [vehicle_number]:
        url = f"https://marketplace.loconav.com/api/v1/vehicles/fuel/interval_data?start_time={start_ts}&end_time={end_ts}&interval=5&vehicle_number={v}"
        r = _try_request(url, headers=headers, timeout=8, retries=2)
        if r is None:
            continue
        try:
            j = r.json()
        except Exception:
            continue
        if not isinstance(j, dict) or "data" not in j:
            continue
        data = j.get("data") or []
        # data expected as list of points sorted by time; if not, try to sort
        points = [p for p in data if isinstance(p, dict)]
        if not points:
            continue

        # sort by timestamp if present
        def _ts(p):
            for k in ("time", "timestamp"):
                if k in p:
                    try:
                        return int(p.get(k))
                    except Exception:
                        pass
            return 0

        points.sort(key=_ts)
        first = points[0]
        last = points[-1]

        def _val(p):
            return _to_float(p.get("value") or p.get("fuel_in_liters") or p.get("fuel"))

        v_first = _val(first)
        v_last = _val(last)
        if v_first is None or v_last is None:
            continue
        # Basic consumed as initial level minus final level
        consumed = v_first - v_last

        # If levels increase (negative consumed), attempt to account for refuels/thefts
        if consumed <= 0:
            try:
                # try to fetch alerts/refuel data for this vehicle/window and adjust
                url_alerts = f"https://marketplace.loconav.com/api/v1/vehicles/fuel?vehicle_number={v}&start_time={start_ts}&end_time={end_ts}"
                ra = _try_request(url_alerts, headers=headers, timeout=8, retries=1)
                refuel_sum = 0.0
                theft_sum = 0.0
                if ra is not None:
                    try:
                        rj = ra.json()
                        refuels = detect_refuel_from_alerts(rj)
                        thefts = detect_theft_from_alerts(rj)
                        for rf in refuels:
                            try:
                                if (
                                    rf.get("timestamp")
                                    and start_ts <= int(rf.get("timestamp")) <= end_ts
                                ):
                                    refuel_sum += float(rf.get("value") or 0)
                            except Exception:
                                continue
                        for tf in thefts:
                            try:
                                if (
                                    tf.get("timestamp")
                                    and start_ts <= int(tf.get("timestamp")) <= end_ts
                                ):
                                    theft_sum += float(tf.get("value") or 0)
                            except Exception:
                                continue
                    except Exception:
                        pass

                adjusted = (v_first + refuel_sum - theft_sum) - v_last
                if adjusted > 0:
                    return adjusted
            except Exception:
                # Fall through to return zero
                pass
        # negative or zero indicates no consumption or could not adjust — return 0
        return max(float(consumed), 0.0)

    return None


def fetch_roadcast_report(
    vehicle_imei: str, start_dt: datetime, end_dt: datetime
) -> Optional[Dict[str, Any]]:
    url = "https://test-track.roadcast.net/api/v1/auth/pull_fuel_report"
    headers = {"Authorization": "Basic QXZpY29ubjpBYmNAMTIzNA=="}
    params = {
        "device_imei": vehicle_imei,
        "from_time": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "to_time": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    response = _try_request(url, params=params, headers=headers, retries=2, timeout=8)
    if response is not None and response.status_code == 200:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return parse_roadcast_report(payload)
        except Exception:
            LOG.debug(
                "fetch_roadcast_report: could not parse primary JSON for %s",
                vehicle_imei,
            )

    try:
        map_url = "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234"
        mapping_response = _try_request(map_url, timeout=8, retries=2)
        if mapping_response is not None and mapping_response.status_code == 200:
            mapping_payload = mapping_response.json()
            for device in (
                mapping_payload.get("data", [])
                if isinstance(mapping_payload, dict)
                else []
            ):
                if str(device.get("deviceImei")) == str(vehicle_imei) or str(
                    device.get("deviceId")
                ) == str(vehicle_imei):
                    mapped = device.get("deviceImei")
                    if not mapped:
                        continue
                    params["device_imei"] = mapped
                    mapped_response = _try_request(
                        url, params=params, headers=headers, retries=2, timeout=8
                    )
                    if (
                        mapped_response is not None
                        and mapped_response.status_code == 200
                    ):
                        try:
                            mapped_payload = mapped_response.json()
                            if isinstance(mapped_payload, dict):
                                return parse_roadcast_report(mapped_payload)
                        except Exception:
                            LOG.debug(
                                "fetch_roadcast_report: parse failure on mapped imei %s",
                                mapped,
                            )
    except Exception:
        LOG.debug("fetch_roadcast_report: mapping fallback failed for %s", vehicle_imei)

    return None


def fetch_loconav_report(
    vehicle_number: str, start_dt: datetime, end_dt: datetime
) -> Optional[Dict[str, Any]]:
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    for candidate in [vehicle_number]:
        url = (
            "https://marketplace.loconav.com/api/v1/vehicles/fuel"
            f"?vehicle_number={candidate}&start_time={start_ts}&end_time={end_ts}"
        )
        response = _try_request(url, headers=headers, timeout=8, retries=2)
        if response is None:
            continue
        try:
            payload = response.json()
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload

    return None


def detect_refuel_from_alerts(alerts_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    if not alerts_json or not isinstance(alerts_json, dict):
        return out
    alerts = alerts_json.get("data") or {}
    if isinstance(alerts, dict):
        alerts = alerts.get("alerts") or alerts
    if not isinstance(alerts, dict):
        alerts = alerts_json.get("alerts") or {}
    refuel = alerts.get("REFUELING_ALERT") or []
    for r in refuel:
        try:
            ts = int(r.get("timestamp"))
        except Exception:
            ts = None
        out.append({"timestamp": ts, "value": _to_float(r.get("value"))})
    return out


def detect_theft_from_alerts(alerts_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    if not alerts_json or not isinstance(alerts_json, dict):
        return out
    alerts = alerts_json.get("data") or {}
    if isinstance(alerts, dict):
        alerts = alerts.get("alerts") or alerts
    if not isinstance(alerts, dict):
        alerts = alerts_json.get("alerts") or {}
    theft = alerts.get("POSSIBLE_FUEL_THEFT_ALERT") or []
    for t in theft:
        try:
            ts = int(t.get("timestamp"))
        except Exception:
            ts = None
        out.append({"timestamp": ts, "value": _to_float(t.get("value"))})
    return out


def detect_suspicious_fuel(tank_capacity: float, fuel_consumed: float) -> bool:
    try:
        if tank_capacity is None or fuel_consumed is None:
            return False
        return float(fuel_consumed) > float(tank_capacity) * 1.2
    except Exception:
        return False
