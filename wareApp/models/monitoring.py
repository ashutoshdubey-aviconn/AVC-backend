"""Pings, monitoring markers and MQTT dead letters."""

from django.db import models
from .setup import Site


class SiteConsumptionPing(models.Model):
    """Table wareApp_siteconsumptionping: site consumption ping. Fields: site, home_gateway_id,
    is_late_ping, consumption_ping_time, updated_on.

    Origin: Ashu
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    home_gateway_id = models.CharField(max_length=200, blank=True, null=True)
    is_late_ping = models.BooleanField(default=False, verbose_name="Late Ping Flag")
    consumption_ping_time = models.DateTimeField(
        blank=True, null=True, verbose_name="Time of Consumption Ping"
    )
    updated_on = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Text for this row in admin and logs: f"{(self.site.site_name if self.site else 'Unknown')} -
        {self.consumption_ping_t.

        Origin: Ashu
        """
        return f"{self.site.site_name if self.site else 'Unknown'} - {self.consumption_ping_time}"


class SiteCeleryPing(models.Model):
    """Table wareApp_siteceleryping: site celery ping. Fields: site, home_gateway_id, leg_id,
    aisle_group, unit_consumption, celery_ping_time, updated_on.

    Origin: Ashu
    """
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    home_gateway_id = models.CharField(max_length=200, blank=True, null=True)
    leg_id = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Leg ID"
    )
    aisle_group = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Aisle Group"
    )
    unit_consumption = models.FloatField(
        blank=True, null=True, verbose_name="Unit Consumption"
    )
    celery_ping_time = models.DateTimeField(
        blank=True, null=True, verbose_name="Time of Celery Ping"
    )
    updated_on = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Text for this row in admin and logs: f"{(self.site.site_name if self.site else 'Unknown')} -
        {self.celery_ping_time}".

        Origin: Ashu
        """
        return f"{self.site.site_name if self.site else 'Unknown'} - {self.celery_ping_time}"


class MonitoringMarker(models.Model):
    """Named timestamps shared by processes (the cache may be per process).

    mqtt_listener_started_at: an MQTT listener (re)started - gateway alarms
    count silence from here at the earliest (our own downtime is not theirs).
    broker_log_read_at: gateway_health --broker-log last read ping lines.

    Origin: Ashu
    """

    name = models.CharField(max_length=50, unique=True)
    at = models.DateTimeField()

    def __str__(self):
        """Text for this row in admin and logs: f'{self.name}: {self.at}'.

        Origin: Ashu
        """
        return f"{self.name}: {self.at}"


class MqttDeadLetter(models.Model):
    """An MQTT packet that could not be processed (kept for inspection/replay).

    Origin: Ashu
    """

    message_type = models.CharField(max_length=50)
    site_id = models.IntegerField(blank=True, null=True)
    gateway_id = models.CharField(max_length=200, blank=True, default="")
    payload = models.TextField()
    error = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["message_type", "is_resolved", "created_at"],
                name="idx_deadletter_type_time",
            ),
            models.Index(fields=["site_id", "created_at"], name="idx_deadletter_site_time"),
        ]

    def __str__(self):
        """Text for this row in admin and logs: '{} site={} {}'.format(self.message_type, self.site_id,
        self.created_at).

        Origin: Ashu
        """
        return "{} site={} {}".format(self.message_type, self.site_id, self.created_at)
