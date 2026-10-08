"""Read-only collection of normalized provider fuel-level samples."""

import logging
from typing import Any, Callable, Dict, Iterable, List

from .providers import (
    extract_roadcast_subscription_expired_errors,
    parse_loconav_current_levels,
    parse_roadcast_current_levels,
)

logger = logging.getLogger("wareApp.dg_fuel.collection")


def target_site(target: Any) -> Any:
    return getattr(target, "site", None) or target


def target_provider(target: Any) -> str:
    if getattr(target, "dg_fuel_enabled", False):
        return (getattr(target, "dg_fuel_provider", None) or "").strip().lower()
    return (getattr(target, "partner_dg_provider", None) or "").strip().lower()


def target_vehicle_number(target: Any) -> str:
    if getattr(target, "dg_fuel_enabled", False):
        return (getattr(target, "dg_fuel_vehicle_number", None) or "").strip()
    return (getattr(target, "partner_dg_fuel_id", None) or "").strip()


def collect_loconav_levels(
    targets: Iterable[Any], fetch_current_levels: Callable[[str], Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch and normalize one current-level payload for each configured target."""
    samples = []
    failed_site_ids = []
    expired_site_ids = []
    for target in targets:
        site = target_site(target)
        vehicle_number = target_vehicle_number(target)
        if not vehicle_number:
            failed_site_ids.append(site.id)
            continue
        try:
            payload = fetch_current_levels(vehicle_number)
            levels = parse_loconav_current_levels(payload)
        except Exception:
            logger.exception(
                "LocoNav collection failed site_id=%s vehicle_number=%s",
                site.id,
                vehicle_number,
            )
            failed_site_ids.append(site.id)
            continue
        matching = [
            level
            for level in levels
            if level["vehicle_number"].replace("-", "").upper()
            == vehicle_number.replace("-", "").upper()
        ]
        samples.extend(
            {
                "site": site,
                "aisle_group": getattr(target, "pk", None) and target,
                "source": "loconav",
                **level,
            }
            for level in matching
        )
        for level in matching:
            logger.info(
                "LocoNav fuel sample collected site_id=%s vehicle_number=%s fuel_liters=%s epoch_ms=%s source=%s",
                site.id,
                level.get("vehicle_number"),
                level.get("fuel_liters"),
                level.get("epoch_ms"),
                "loconav",
            )
        if not matching:
            expired_site_ids.append(site.id)
            logger.warning(
                "LocoNav device unavailable or expired site_id=%s vehicle_number=%s expected_vehicle_number=%s",
                site.id,
                vehicle_number,
                vehicle_number,
            )
    return {
        "samples": samples,
        "failed_site_ids": failed_site_ids,
        "expired_site_ids": expired_site_ids,
    }


def collect_roadcast_levels(
    targets: Iterable[Any],
    fetch_pull_api: Callable[[], Any],
    reference_date=None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch Roadcast once, map its samples to configured targets, and report gaps."""
    target_by_imei = {
        target_vehicle_number(target): target
        for target in targets
        if target_vehicle_number(target)
    }
    try:
        payload = fetch_pull_api()
        levels = parse_roadcast_current_levels(
            payload, target_by_imei, reference_date=reference_date
        )
        subscription_expired_errors = extract_roadcast_subscription_expired_errors(
            payload
        )
    except Exception:
        logger.exception(
            "Roadcast pull_api collection failed configured_sites=%s",
            len(target_by_imei),
        )
        return {
            "samples": [],
            "missing_vehicle_ids": [],
            "expired_vehicle_ids": [],
            "subscription_expired_errors": [],
            "provider_request_failed": True,
        }

    current_levels = [level for level in levels if level.get("is_current_sample")]
    diagnostic_levels = [
        level for level in levels if not level.get("is_current_sample")
    ]
    returned_ids = {level["vehicle_number"] for level in levels}
    missing_vehicle_ids = sorted(set(target_by_imei) - returned_ids)
    stale_vehicle_ids = sorted({level["vehicle_number"] for level in diagnostic_levels})
    for vehicle_id in missing_vehicle_ids:
        logger.warning(
            "Roadcast device unavailable or expired vehicle_id=%s known_vehicle_ids=%s",
            vehicle_id,
            sorted(target_by_imei),
        )
    samples = [
        {
            "site": target_site(target_by_imei[level["vehicle_number"]]),
            "aisle_group": getattr(target_by_imei[level["vehicle_number"]], "pk", None)
            and target_by_imei[level["vehicle_number"]],
            "source": "roadcast",
            **level,
        }
        for level in current_levels
    ]
    for level in current_levels:
        logger.info(
            "Roadcast fuel sample collected site_id=%s vehicle_number=%s fuel_liters=%s epoch_ms=%s source=%s",
            target_site(target_by_imei[level["vehicle_number"]]).id,
            level.get("vehicle_number"),
            level.get("fuel_liters"),
            level.get("epoch_ms"),
            "roadcast",
        )
    for level in diagnostic_levels:
        logger.info(
            "Roadcast diagnostic telemetry site_id=%s vehicle_number=%s fuel_liters=%s epoch_ms=%s telemetry_state=%s provider_status=%s source=%s",
            target_site(target_by_imei[level["vehicle_number"]]).id,
            level.get("vehicle_number"),
            level.get("fuel_liters"),
            level.get("epoch_ms"),
            level.get("telemetry_state"),
            level.get("provider_status"),
            "roadcast",
        )
    return {
        "samples": samples,
        "missing_vehicle_ids": missing_vehicle_ids,
        "stale_vehicle_ids": stale_vehicle_ids,
        "expired_vehicle_ids": missing_vehicle_ids,
        "subscription_expired_errors": subscription_expired_errors,
        "provider_request_failed": False,
    }
