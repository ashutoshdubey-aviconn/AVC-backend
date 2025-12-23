from datetime import date, timedelta
from collections import defaultdict
from django.db.models import F
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from wareApp.models import *

from django.db.models import Sum

start_date = date(2025, 5, 19)
end_date = date(2025, 5, 21)
site_id = 54

# Step 1: Get all readings for the 3-day range
all_readings = DailySiteReading.objects.filter(
    associated_Site_id=site_id,
    reading_for__range=(start_date, end_date)
)

# Step 2: Group readings by leg_id and collect by date
grouped = defaultdict(dict)
for reading in all_readings:
    grouped[reading.leg_id][reading.reading_for] = reading

# Step 3: Prepare the 3 dates
date_list = [start_date + timedelta(days=i) for i in range(3)]

# Step 4: Process each leg
for leg_id, records_by_date in grouped.items():
    # Total from available records
    total = sum(r.unit_consumption for r in records_by_date.values())
    per_day_value = round(total / 3, 2)

    for day in date_list:
        record = records_by_date.get(day)

        if record:
            # Update existing record
            record.unit_consumption = per_day_value
            record.save()
        else:
            # Create missing record
            DailySiteReading.objects.create(
                associated_Site_id=site_id,
                leg_id=leg_id,
                reading_for=day,
                unit_consumption=per_day_value
            )

