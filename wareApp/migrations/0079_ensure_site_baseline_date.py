from django.db import migrations, models


def _ensure_site_baseline_date(apps, schema_editor):
    table_name = "wareApp_site"
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }
        if "baseline_date" in columns:
            return
    field = models.DateTimeField(blank=True, null=True)
    field.set_attributes_from_name("baseline_date")
    Site = apps.get_model("wareApp", "Site")
    schema_editor.add_field(Site, field)


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0078_add_dgfuel_uniqueness_constraints"),
    ]

    operations = [
        migrations.RunPython(_ensure_site_baseline_date, reverse_code=migrations.RunPython.noop),
    ]
