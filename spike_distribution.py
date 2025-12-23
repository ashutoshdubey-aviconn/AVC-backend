import os
import django
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')
django.setup()
import random
from django.db.models import F

from wareApp.models import Site, AisleGroup, DailySiteReading

def get_consumption_range(room_id, date_from, days):
    try:
        cons = DailySiteReading.objects.get(
            aisle_group_id=room_id,
            reading_for=date_from.date()
        ).unit_consumption
    except DailySiteReading.DoesNotExist:
        cons = 0  # Or handle error as needed

    per_day_cons = cons / days if days else 0
    return [per_day_cons - 2.5, per_day_cons + 2.5]

def reduce_spike(site_id, date_from, spike_date ,days):
    site = Site.objects.get(id=site_id)
    
    rooms = AisleGroup.objects.filter(site=site)
    if(site_id == 34):
        print("inside 34")
        rooms = AisleGroup.objects.filter(id__in = [710,259, 260, 261, 276])
        rooms = AisleGroup.objects.filter(id__in = room)
        site = Site.objects.get(id=29)
    print(len(rooms), site.site_name)
    for i in rooms:
        per_day_cons = get_consumption_range(i, spike_date, days)
        print(f'For room {i.aisleGroupName}, per day consumption will be {per_day_cons}')
        for j in range(days):
            date_iter = date_from + timedelta(days=j)
            DailySiteReading.objects.update_or_create(
                aisle_group_id=i.id,
                associated_Site=site,
                reading_for=date_iter,
                is_visible=True,
                leg_id=i.id,
                defaults={
                    'unit_consumption': random.uniform(per_day_cons[0], per_day_cons[1])
                }
            )
            print(f'Updated consumption to {per_day_cons} for date {date_iter}')

if __name__ == '__main__':
    site_id = int(input('Enter the site ID: '))
    spike_date = input('Enter the date of spike (e.g. 01-June-25): ')
    days = int(input('Enter the number of days to spread the spike over: '))
    date_from = input('Enter the date from which the spike is to be distributed (e.g. 01-June-25): ')

    try:
        date_from = datetime.strptime(date_from, '%d-%B-%y')
        spike_date = datetime.strptime(spike_date, '%d-%B-%y')
    except ValueError:
        print('Invalid date format! Please use DD-Month-YY, e.g. 01-June-25')
        exit(1)

    reduce_spike(site_id, date_from, spike_date, days)
    d = DailySiteReading.objects.filter(associated_Site_id = 127, reading_for__range = (date_from, spike_date), unit_consumption__lt = 0)
    if d.exists():
        d.update(unit_consumption = F('unit_consumption') * (-1))

