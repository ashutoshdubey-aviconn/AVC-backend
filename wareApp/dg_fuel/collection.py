"""Read-only collection of normalized provider fuel-level samples."""

import logging
from typing import Any, Callable, Dict, Iterable, List

from .providers import parse_loconav_current_levels, parse_roadcast_current_levels

logger = logging.getLogger("wareApp.dg_fuel.collection")


def collect_loconav_levels(
    sites: Iterable[Any], fetch_current_levels: Callable[[str], Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch and normalize one current-level payload for each LocoNav site."""
    samples = []
    failed_site_ids = []
    expired_site_ids = []
    for site in sites:
        vehicle_number = (getattr(site, "partner_dg_fuel_id", None) or "").strip()
        if not vehicle_number:
            failed_site_ids.append(site.id)
            continue
        try:
            payload = fetch_current_levels(vehicle_number)
            levels = parse_loconav_current_levels(payload)
        except Exception:
            logger.exception("LocoNav collection failed for site_id=%s", site.id)
            failed_site_ids.append(site.id)
            continue
        matching = [
            level
            for level in levels
            if level["vehicle_number"].replace("-", "").upper()
            == vehicle_number.replace("-", "").upper()
        ]
        samples.extend({"site": site, "source": "loconav", **level} for level in matching)
        if not matching:
            expired_site_ids.append(site.id)
            logger.warning(
                "LocoNav device unavailable or expired for site_id=%s vehicle_number=%s",
                site.id,
                vehicle_number,
            )
    return {
        "samples": samples,
        "failed_site_ids": failed_site_ids,
        "expired_site_ids": expired_site_ids,
    }


def collect_roadcast_levels(
    sites: Iterable[Any], fetch_pull_api: Callable[[], Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch Roadcast once, map its samples to configured sites, and report gaps."""
    site_by_imei = {
        str(site.partner_dg_fuel_id).strip(): site
        for site in sites
        if getattr(site, "partner_dg_fuel_id", None)
    }
    try:
        payload = fetch_pull_api()
        levels = parse_roadcast_current_levels(payload, site_by_imei)
    except Exception:
        logger.exception("Roadcast pull_api collection failed")
        return {
            "samples": [],
            "missing_vehicle_ids": [],
            "expired_vehicle_ids": [],
            "provider_request_failed": True,
        }

    returned_ids = {level["vehicle_number"] for level in levels}
    missing_vehicle_ids = sorted(set(site_by_imei) - returned_ids)
    for vehicle_id in missing_vehicle_ids:
        logger.warning(
            "Roadcast device unavailable or expired from pull_api vehicle_id=%s",
            vehicle_id,
        )
    samples = [
        {"site": site_by_imei[level["vehicle_number"]], "source": "roadcast", **level}
        for level in levels
    ]
    return {
        "samples": samples,
        "missing_vehicle_ids": missing_vehicle_ids,
        "expired_vehicle_ids": missing_vehicle_ids,
        "provider_request_failed": False,
    }