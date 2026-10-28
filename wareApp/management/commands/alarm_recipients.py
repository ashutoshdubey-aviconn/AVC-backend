"""Show which location team and e-mail addresses each site's alarms go to.

    python manage.py alarm_recipients              every site
    python manage.py alarm_recipients --site 183   one site
    python manage.py alarm_recipients --unmatched  sites without a location team

Lists come from wareApp/mqtt/services/alarm_recipients.py. On a test server
ALARM_EMAIL_OVERRIDE_TO still replaces these addresses when e-mails are sent.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from wareApp.models import Site
from wareApp.mqtt.services import alarm_policy


class Command(BaseCommand):
    help = "Show each site's location team and alarm e-mail recipients."

    def add_arguments(self, parser):
        parser.add_argument("--site", type=int, action="append", help="Site id (repeatable)")
        parser.add_argument("--unmatched", action="store_true", help="Only sites without a location team")

    def handle(self, *args, site=None, unmatched=False, **options):
        alarm_policy.clear_cache()
        sites = Site.objects.order_by("id")
        if site:
            sites = sites.filter(id__in=site)
        rows = 0
        for item in sites.values("id", "site_name", "location"):
            location = alarm_policy.site_location(item["id"])
            if unmatched and location:
                continue
            rows += 1
            self.stdout.write(
                f"{item['id']:>4}  {(item['site_name'] or '')[:40]:<40}  "
                f"{(item['location'] or '-')[:28]:<28}  {location or '(no location team)':<18}  "
                f"{', '.join(alarm_policy.recipients(item['id'])) or '-'}"
            )
        self.stdout.write(f"{rows} sites")
        override = getattr(settings, "ALARM_EMAIL_OVERRIDE_TO", [])
        if override:
            self.stdout.write(f"Note: ALARM_EMAIL_OVERRIDE_TO is set here; e-mails go only to {', '.join(override)}")
