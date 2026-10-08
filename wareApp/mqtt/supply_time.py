import logging
from datetime import datetime, timedelta

from django.db.models import F, Sum

from wareApp.models import MonthlyLoadSharePercentage, SupplyLoadTimeShare


logger = logging.getLogger(__name__)


def _parse_supply_time_message(message):
    payload = message.strip()
    if payload.startswith("b'") and payload.endswith("'"):
        payload = payload[2:-1]

    fields = {}
    for field in payload.split(","):
        key, separator, value = field.partition(":")
        if not separator:
            raise ValueError(f"Invalid SupplyTime field: {field!r}")
        fields[key.strip().lower()] = value.strip()

    try:
        source = int(fields["source"])
        run_time = float(fields["runtime"])
        observed_at = datetime.fromisoformat(fields["time"])
    except KeyError as error:
        raise ValueError(f"Missing SupplyTime field: {error.args[0]}") from error

    return source, run_time, observed_at


def _update_monthly_share_if_due(site, location_id, last_runtime_entry, now):
    if not last_runtime_entry or now.month == last_runtime_entry.reading_from.month:
        return

    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    monthly_totals = (
        SupplyLoadTimeShare.objects.filter(
            site=location_id,
            reading_from__gte=previous_month_start,
            reading_from__lt=current_month_start,
        )
        .values("power_source")
        .annotate(total_runtime=Sum("hourly_run_time"))
    )
    total_time = sum(entry["total_runtime"] for entry in monthly_totals)
    if not total_time:
        return

    for entry in monthly_totals:
        share = (entry["total_runtime"] / total_time) * 100
        monthly_share = MonthlyLoadSharePercentage.objects.filter(
            site=site,
            power_source=entry["power_source"],
            for_month=previous_month_start.strftime("%m %Y"),
        )
        if not monthly_share.update(monthly_time_based_percentage=share):
            MonthlyLoadSharePercentage.objects.create(
                site=site,
                power_source=entry["power_source"],
                monthly_time_based_percentage=share,
                for_month=previous_month_start.strftime("%m %Y"),
            )


def handle_supply_time_message(
    client, site, location_id, gateway_id, message, publish_recovery=None
):
    """Persist one SupplyTime packet and request gateway recovery for a detected gap."""
    try:
        source, source_run_time, observed_at = _parse_supply_time_message(message)
        hour_start = observed_at.replace(minute=0, second=0, microsecond=0)
        hour_end = observed_at.replace(minute=59, second=59, microsecond=0)
        run_time = SupplyLoadTimeShare.objects.filter(
            site=location_id, power_source=source
        )
        current_hour = run_time.filter(
            reading_from__gte=hour_start,
            reading_from__lte=hour_end,
        )
        if current_hour.update(hourly_run_time=F("hourly_run_time") + source_run_time):
            logger.info(
                "Updated SupplyTime for site %s, source %s, hour %s",
                location_id,
                source,
                hour_start,
            )
            return

        last_runtime_entry = run_time.order_by("-reading_from", "-id").first()
        _update_monthly_share_if_due(
            site, location_id, last_runtime_entry, datetime.now()
        )
        previous_hour = run_time.filter(
            reading_from__gte=hour_start - timedelta(hours=1),
            reading_from__lte=hour_end - timedelta(hours=1),
        )
        if previous_hour.exists() or not last_runtime_entry:
            SupplyLoadTimeShare.objects.create(
                site=site,
                power_source=source,
                hourly_run_time=source_run_time,
                reading_from=hour_start,
                reading_to=hour_end,
            )
            logger.info(
                "Created SupplyTime for site %s, source %s, hour %s",
                location_id,
                source,
                hour_start,
            )
            return

        loss_time = (datetime.now() - last_runtime_entry.reading_from).total_seconds()
        recovery_topic = (
            f"/Acclivate/iOmniControl/{location_id}/{gateway_id}/in/sync/loadTime/state"
        )
        recovery_message = (
            f"Power_source : {source}, Missed_consumption_time_in_secs : {loss_time}, "
            f"Last_synced_hour : {last_runtime_entry.reading_from:%Y-%m-%d %H:%M:%S.%f}"
        )
        if publish_recovery:
            publish_recovery(recovery_topic, recovery_message)
        else:
            client.publish(recovery_topic, recovery_message, qos=0, retain=False)
        logger.warning(
            "Requested SupplyTime recovery for site %s, source %s from gateway %s",
            location_id,
            source,
            gateway_id,
        )
    except Exception:
        logger.exception(
            "Queue1 SupplyTime processing failed for site %s from gateway %s",
            location_id,
            gateway_id,
        )