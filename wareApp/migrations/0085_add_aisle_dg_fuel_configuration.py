from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0084_add_load_data_rollup_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="aislegroup",
            name="dg_fuel_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="aislegroup",
            name="dg_fuel_provider",
            field=models.CharField(
                blank=True,
                choices=[("loconav", "LocoNav"), ("roadcast", "Roadcast")],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="aislegroup",
            name="dg_fuel_vehicle_number",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="dgunitconsumption",
            name="fuel_provider",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="dgunitconsumption",
            name="fuel_vehicle_number",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="dgfuelconsumptiondata",
            name="aisle_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                to="wareApp.aislegroup",
            ),
        ),
        migrations.AddField(
            model_name="dgfuelalertsdata",
            name="aisle_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                to="wareApp.aislegroup",
            ),
        ),
    ]
