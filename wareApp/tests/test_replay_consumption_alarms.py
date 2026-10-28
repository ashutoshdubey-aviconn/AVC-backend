"""manage.py replay_consumption_alarms: day-by-day alarm replay."""

import csv
import os
import tempfile
from datetime import date
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from wareApp.models import AisleGroup, AlarmNotifications, DailySiteReading, Site, SiteBaseline
from wareApp.mqtt.services import consumption_alarms


class ReplayConsumptionAlarmsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.mail_site = self.make_site("Farrukhnagar test", bypass=100.0)
        self.quiet_site = self.make_site("Other site", bypass=100.0)
        # day 1: bypassed (>= 100), day 2: high (>= 75 % of 48), day 3: normal
        for site, aisle in (self.mail_site, self.quiet_site):
            for day, units in ((1, 150.0), (2, 40.0), (3, 10.0)):
                DailySiteReading.objects.create(
                    associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
                    unit_consumption=units, daily_baseline_value=48.0,
                    reading_for=date(2026, 10, day), is_visible=True,
                )
        real = mock.patch.object(consumption_alarms, "notify")
        self.real_notify = real.start()
        self.addCleanup(real.stop)

    def make_site(self, name, bypass):
        site = Site.objects.create(site_name=name, site_type=1, is_live=True,
                                   bypass_consumption_units=bypass)
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="A1", is_active=True)
        aisle.refresh_from_db()
        SiteBaseline.objects.create(associated_site_id=site, leg_id=aisle.attached_leg_id,
                                    baseline_value=48.0, working_hours=24)
        return site, aisle

    def run_command(self, *extra):
        out = StringIO()
        mail_site = self.mail_site[0]
        call_command(
            "replay_consumption_alarms", "--from", "2026-10-01", "--to", "2026-10-03",
            "--site", str(mail_site.id), "--site", str(self.quiet_site[0].id),
            "--email-site", str(mail_site.id), *extra, stdout=out,
        )
        return out.getvalue()

    def test_dry_run_stores_and_mails_nothing(self):
        output = self.run_command()
        self.assertIn("would store (dry run", output)
        self.assertIn("4 alarms", output)
        self.assertFalse(AlarmNotifications.objects.exists())
        self.real_notify.assert_not_called()

    def test_apply_stores_and_mails_only_chosen_sites(self):
        output = self.run_command("--apply")
        self.assertIn("stored 4 alarms", output)
        self.assertIn("Bypassed: 2", output)
        self.assertIn("High Consumption: 2", output)
        self.assertEqual(AlarmNotifications.objects.count(), 4)
        self.assertEqual(self.real_notify.call_count, 2)
        mailed_sites = {call.args[2] for call in self.real_notify.call_args_list}
        self.assertEqual(mailed_sites, {self.mail_site[0].id})
        self.assertIn("e-mails queued: 2", output)

    def test_rerun_does_not_duplicate(self):
        self.run_command("--apply")
        output = self.run_command("--apply")
        self.assertIn("stored 0 alarms", output)
        self.assertEqual(AlarmNotifications.objects.count(), 4)

    def test_mail_limit(self):
        output = self.run_command("--apply", "--max-emails", "1")
        self.assertEqual(self.real_notify.call_count, 1)
        self.assertIn("limit 1 reached, 1 not sent", output)

    def test_report_lists_every_alarm_with_mail_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "replay.csv")
            self.run_command("--apply", "--report", path)
            with open(path) as fh:
                rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 4)
        by_site = {(r["site_name"], r["date"]): r for r in rows}
        self.assertEqual(by_site[("Farrukhnagar test", "2026-10-01")]["alarm"], "Bypassed")
        self.assertEqual(by_site[("Farrukhnagar test", "2026-10-01")]["email"], "e-mail")
        self.assertEqual(by_site[("Other site", "2026-10-02")]["email"], "no e-mail")
