from django.utils import timezone

from wareApp.models import AisleSyncRecoveryStatus


def mark_sync_healthy(site, home_gateway_id, aisle_group, observed_at):
    return AisleSyncRecoveryStatus.objects.update_or_create(
        site=site,
        home_gateway_id=str(home_gateway_id),
        aisle_group=aisle_group,
        defaults={
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "healthy",
            "is_sync_gone": False,
            "recovery_requested": False,
            "recovery_received": False,
            "last_sync_at": observed_at,
            "last_error": None,
        },
    )


def mark_recovery_requested(
    site, home_gateway_id, aisle_group, missing_from, missing_to
):
    return AisleSyncRecoveryStatus.objects.update_or_create(
        site=site,
        home_gateway_id=str(home_gateway_id),
        aisle_group=aisle_group,
        defaults={
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "recovery_requested",
            "is_sync_gone": True,
            "recovery_requested": True,
            "recovery_received": False,
            "last_recovery_requested_at": timezone.now(),
            "expected_from": missing_from,
            "expected_to": missing_to,
            "missing_slots": 1,
        },
    )


def mark_recovery_received(site, home_gateway_id, aisle_group):
    return AisleSyncRecoveryStatus.objects.update_or_create(
        site=site,
        home_gateway_id=str(home_gateway_id),
        aisle_group=aisle_group,
        defaults={
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "recovery_received",
            "is_sync_gone": True,
            "recovery_requested": True,
            "recovery_received": True,
            "last_recovery_received_at": timezone.now(),
        },
    )


def mark_recovered(site, home_gateway_id, aisle_group, recovered_slots):
    return AisleSyncRecoveryStatus.objects.update_or_create(
        site=site,
        home_gateway_id=str(home_gateway_id),
        aisle_group=aisle_group,
        defaults={
            "leg_id": str(aisle_group.attached_leg_id),
            "sync_status": "recovered",
            "is_sync_gone": False,
            "recovery_requested": False,
            "recovery_received": True,
            "last_recovery_applied_at": timezone.now(),
            "missing_slots": 0,
            "recovered_slots": recovered_slots,
            "last_error": None,
        },
    )
