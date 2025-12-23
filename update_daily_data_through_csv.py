from django.db.models import F
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
import csv
from datetime import datetime
from wareApp.models import AisleGroup, DailySiteReading, Site

CSV_FILE_PATH = './energy_data8-Sep-2025.csv'
SITE_ID = 114  # Set your actual site ID here

with open(CSV_FILE_PATH, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        reading_date = datetime.strptime(row['Date'], '%d-%b-%Y').date()

        for room_name, consumption_str in row.items():
            if room_name in ['Date', 'TotalConsumption']:
                continue  # Skip

            try:
                consumption = float(consumption_str)
            except (ValueError, TypeError):
                consumption = 0.0

            # Match AisleGroup by name (assuming room_name == aisleGroupName)
            try:
                aisle = AisleGroup.objects.get(aisleGroupName=room_name, site__id=SITE_ID)
            except AisleGroup.DoesNotExist:
                print(f"⚠️ No AisleGroup found for: {room_name}")
                continue

            dsr, created = DailySiteReading.objects.update_or_create(
                associated_Site=aisle.site,
                aisle_group=aisle,
                leg_id = aisle.id,
                reading_for=reading_date,
                defaults={
                    'unit_consumption': consumption,
                    'is_visible': True  # or set based on your condition
                }
            )

            print(f"{'✅ Created' if created else '🌀 Updated'}: {room_name} on {reading_date} with {consumption} kWh")

