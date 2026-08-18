"""Utilities to find and reconcile duplicate DgFuelConsumptionData rows.

This module provides a small, deterministic dedupe routine that keeps the
earliest-inserted row (by `id`) and deletes any additional rows for the
same site/vehicle/epoch_time. It is intentionally conservative and meant
for use in backfill/reconciliation flows.
"""

from typing import Tuple

from wareApp.models import DgFuelConsumptionData, Site


def dedupe_dg_consumption(site: Site, vehicle_number: str, epoch_time: str) -> int:
    """Remove duplicate `DgFuelConsumptionData` records for the given key.

    Keeps the earliest-inserted row (lowest `id`) and deletes the rest.

    Returns the number of rows deleted.
    """
    qs = DgFuelConsumptionData.objects.filter(
        site=site, vehicle_number=vehicle_number, epoch_time=epoch_time
    ).order_by("id")
    total = qs.count()
    if total <= 1:
        return 0
    keep = qs.first()
    to_delete = qs.exclude(pk=keep.pk)
    deleted_count, _ = to_delete.delete()
    return deleted_count
