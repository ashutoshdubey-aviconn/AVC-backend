from django.db import migrations, models


def forward(apps, schema_editor):
    Site = apps.get_model("wareApp", "Site")
    for s in Site.objects.all():
        try:
            pid = (s.partner_dg_fuel_id or "").strip()
            if pid and pid.isdigit():
                s.partner_dg_provider = "roadcast"
            else:
                # default to loconav for existing non-numeric ids
                s.partner_dg_provider = "loconav"
            s.save()
        except Exception:
            # best-effort backfill; skip on error
            continue


def reverse(apps, schema_editor):
    Site = apps.get_model("wareApp", "Site")
    Site.objects.update(partner_dg_provider=None)


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0074_add_fuel_data_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="partner_dg_provider",
            field=models.CharField(max_length=32, null=True, blank=True),
        ),
        migrations.RunPython(forward, reverse),
    ]
