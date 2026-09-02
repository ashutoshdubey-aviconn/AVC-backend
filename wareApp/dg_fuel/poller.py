"""DG-fuel level polling orchestration with an explicit dry-run mode."""

import logging
from typing import Any, Callable, Dict, Iterable, List

from .collection import collect_loconav_levels, collect_roadcast_levels

logger = logging.getLogger("wareApp.dg_fuel.poller")


def collect_level_cycle(
    sites: Iterable[Any],
    fetch_loconav: Callable[[str], Any],
    fetch_roadcast: Callable[[], Any],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Collect provider fuel levels and optionally persist normalized samples."""
    loconav_sites = []
    roadcast_sites = []
    skipped_sites = []
    for site in sites:
        provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
        if provider == "loconav":
            loconav_sites.append(site)
        elif provider == "roadcast":
            roadcast_sites.append(site)
        else:
            skipped_sites.append(site.id)
            logger.warning("Skipping site_id=%s with unsupported provider=%r", site.id, provider)

    loconav_result = collect_loconav_levels(loconav_sites, fetch_loconav)
    roadcast_result = collect_roadcast_levels(roadcast_sites, fetch_roadcast)
    samples = loconav_result["samples"] + roadcast_result["samples"]
    inserted = 0
    existing = 0
    if not dry_run:
        from .ingestion import record_fuel_level

        for sample in samples:
            _, created = record_fuel_level(
                site=sample["site"],
                vehicle_number=sample["vehicle_number"],
                fuel_liters=sample["fuel_liters"],
                epoch_value=sample["epoch_ms"],
                source=sample["source"],
            )
            inserted += int(created)
            existing += int(not created)

    result = {
        "dry_run": dry_run,
        "proposed_samples": len(samples),
        "inserted": inserted,
        "existing": existing,
        "loconav_failed_site_ids": loconav_result["failed_site_ids"],
        "loconav_expired_site_ids": loconav_result["expired_site_ids"],
        "roadcast_missing_vehicle_ids": roadcast_result["missing_vehicle_ids"],
        "roadcast_expired_vehicle_ids": roadcast_result["expired_vehicle_ids"],
        "roadcast_provider_request_failed": roadcast_result[
            "provider_request_failed"
        ],
        "unavailable_device_ids": sorted(
            {
                *loconav_result["expired_site_ids"],
                *roadcast_result["expired_vehicle_ids"],
            }
        ),
        "skipped_site_ids": skipped_sites,
    }
    logger.info("DG fuel level cycle result=%s", result)
    return result