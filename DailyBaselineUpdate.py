import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')
django.setup()
from django.db.models import F,Q

# Importing the required models and libraries
import requests
import datetime
from wareApp.models import *

sites = eval(input("enter all the sites you want to update the daily baseline for : "))
start_date = input("enter the start date (YYYY-MM-DD) : ")
end_date = input("enter the end date (YYYY-MM-DD) : ")

for site in sites:
    a = AisleGroup.objects.filter(site_id = site)

    for i in a:
        date = datetime.strptime(start_date, "%Y-%m-%d")
        d = DailySiteReading.objects.filter(associated_Site_id = site, reading_for__range = (datetime.strptime(start_date, "%Y-%m-%d"), datetime.strptime(end_date, "%Y-%m-%d")), leg_id = i.id)
        if d.exists():
            baseline = SiteBaseline.objects.filter(associated_site_id_id = site, aisle_group_id = i.id).filter(baseline_from__lte=date).filter(Q(baseline_to__gte=date) | Q(baseline_to__isnull=True))
            if baseline.exists():
                baseline = baseline.last()
                d.update(daily_baseline_value = baseline.baseline_value)
                d.update(energy_saved = F('daily_baseline_value') - F('unit_consumption'))

