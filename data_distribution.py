'''
the Script is used to distribute the data in the database. if there's any spike in the data, the function reduce_spike will be called to reduce the spike in the data and distribute it evenly.
'''

import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')
django.setup()

from django.db.models import Avg, Max
from wareApp.models import *
from datetime import datetime, timedelta, date
import random

def get_consumption_range(room_id, date_from, date_to):
    print(date_from.date() - timedelta(days=15))
    # Get the maximum and minimum values of the consumption
    max_cons = DailySiteReading.objects.filter(
        aisle_group_id = room_id,
        reading_for__gte = date_from,
        #reading_for__gt=date_from.date() - timedelta(days=15),
        reading_for__lt=date_to
    ).aggregate(Max('unit_consumption'))['unit_consumption__max']

    min_cons = DailySiteReading.objects.filter(
        aisle_group_id = room_id,
        reading_for__gte = date_from,
        #reading_for__gt=date_from.date() - timedelta(days=15),
        reading_for__lt=date_to
    ).aggregate(Avg('unit_consumption'))['unit_consumption__avg']
    if max_cons == None:
        max_cons = 0
    if min_cons == None:
        min_cons = 0

    return [min_cons, max_cons]


def reduce_spike(site_id, date_from, to_date, date_of_spike, days):
    site = Site.objects.get(id=site_id)
    rooms = AisleGroup.objects.filter(site=site)
    print(rooms)
    if site_id == 34:
        rooms = [710,259, 260, 261, 276]
    for i in rooms:
        cons = get_consumption_range(i.id, date_from, date_to)
        print(f'for room named {i.aisleGroupName}')
        for j in range(days):
            date = date_of_spike + timedelta(days=j)
            consVal = random.uniform(cons[0], cons[1])
            DailySiteReading.objects.update_or_create(
                aisle_group_id=i.id,
                associated_Site = site,
                reading_for=date,
                is_visible = True,
                leg_id = i.id,
                defaults={
                    'unit_consumption': consVal
                }
            )
            print(f'updated consumption to be {consVal} for date {date}')

    ...

site = int(input('Enter the site id: '))
date_from = input('Enter the starting date of a correct sample ')
date_to = input('Enter the end date of a correct sample ')
date_of_spike = input('Enter the date from which the spike is to be reduced ') 
days = int(input('Enter the number of days for which the spike is to be reduced: '))
reduce_spike(site, datetime.strptime(date_from, '%Y-%m-%d'), datetime.strptime(date_to, '%Y-%m-%d'), datetime.strptime(date_of_spike, '%Y-%m-%d'), days)
