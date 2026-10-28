"""Gateway health: read pings from the Mosquitto log and check alarms 14 / 15 / 16.

    python manage.py gateway_health                       check alarms (beat does this every 5 min)
    python manage.py gateway_health --broker-log /var/log/mosquitto/mosquitto.log
                                                          read new ping lines first, then check
    python manage.py gateway_health --broker-log FILE --from-start --dry-run
                                                          what would be raised / cleared; rolls back, no e-mail

The broker log is readable only by mosquitto / root, so --broker-log runs from
root's cron (every 5 min). Without fresh ping lines a gateway silent for the
threshold counts as disconnected (15); with them 15 and 16 are told apart.
"""

from unittest import mock

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction

from wareApp.mqtt.services import gateway_health


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Read gateway pings from the Mosquitto log and raise / clear alarms 14, 15, 16."

    def add_arguments(self, parser):
        parser.add_argument("--broker-log", help="Mosquitto log to read ping lines from")
        parser.add_argument("--from-start", action="store_true", help="Read the whole log file")
        parser.add_argument("--dry-run", action="store_true", help="Show the result, store nothing, send no e-mail")

    def handle(self, *args, broker_log=None, from_start=False, dry_run=False, **options):
        mails = []
        ping_marker = cache.get(gateway_health.PING_READ_KEY)
        try:
            with transaction.atomic(), mock.patch.object(
                gateway_health, "notify", side_effect=lambda *a: mails.append(a)
            ) if dry_run else _nothing():
                if broker_log:
                    alive = gateway_health.read_broker_log(
                        broker_log, from_start=from_start, remember=not dry_run
                    )
                    stored = gateway_health.store_pings(alive)
                    self.stdout.write(f"broker log: {len(alive)} clients alive, {stored} gateways updated")
                report = gateway_health.evaluate()
                self.stdout.write(f"alarms: {report}")
                for label, items in (("raised", report.raised), ("cleared", report.cleared)):
                    for site_id, alarm_type, object_id in items:
                        self.stdout.write(f"  {label}: site={site_id} type={alarm_type} object={object_id}")
                if dry_run:
                    for mail in mails:
                        self.stdout.write(f"  would e-mail: {mail[1]} - site {mail[2]}")
                    raise _Rollback
        except _Rollback:
            # Leave the live ping marker as it was.
            if ping_marker is None:
                cache.delete(gateway_health.PING_READ_KEY)
            else:
                cache.set(gateway_health.PING_READ_KEY, ping_marker, None)
            self.stdout.write("dry run: nothing stored, no e-mail sent")


class _nothing:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
