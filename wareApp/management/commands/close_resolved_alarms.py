"""Close alarms that are no longer happening (beat does this every 5 minutes).

    python manage.py close_resolved_alarms --dry-run   counts per rule, nothing changed
    python manage.py close_resolved_alarms             close them now

Rules: wareApp/mqtt/services/alarm_closer.py.
"""

from django.core.management.base import BaseCommand

from wareApp.mqtt.services import alarm_closer


class Command(BaseCommand):
    """manage.py close_resolved_alarms: Close alarms that are no longer happening.

    Origin: Ashu
    """
    help = "Close alarms that are no longer happening."

    def add_arguments(self, parser):
        """Command-line options: --dry-run.

        Origin: Ashu
        """
        parser.add_argument("--dry-run", action="store_true", help="Only count")

    def handle(self, *args, dry_run=False, **options):
        """Runs manage.py close_resolved_alarms: Close alarms that are no longer happening.

        Origin: Ashu
        """
        counts = alarm_closer.close_resolved(dry_run=dry_run)
        for label, count in counts.items():
            self.stdout.write(f"{'would close' if dry_run else 'closed'} {count:>6}  {label}")
        self.stdout.write(f"total {sum(counts.values())}{' (dry run)' if dry_run else ''}")
