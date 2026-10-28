"""Duplicate detection for DG fuel consumption rows."""

from wareApp.models import DgFuelConsumptionData, Site


def dedupe_dg_consumption(site: Site, vehicle_number: str, epoch_time: str) -> int:
    """Remove duplicate DG fuel rows for the same site/vehicle/epoch key."""
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