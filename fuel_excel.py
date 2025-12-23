import pandas
import os
import requests
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from wareApp.models import *
from wareApp.views import *
import time
from datetime import datetime, timedelta

data = {"site_id":"35","start_date":"2025-10-01","end_date":"2025-10-31"}

#idata = request.data
site_id = data.get("site_id")
site = Site.objects.get(id=site_id)
from_date = datetime.strptime(data.get("start_date"), "%Y-%m-%d")
end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")
vehical_number = site.partner_dg_fuel_id.upper()

fuel_absolute_data = [
    {
        "Date": i.created.strftime("%d-%b-%Y"),
        "Time": f"{i.created.hour}:{i.created.minute}",
        "Fuel_Level": round(i.fuel_consumption, 2),
    }
                for i in DgFuelConsumptionData.objects.filter(
                    site=site_id,
                    created__date__range=(from_date.date(), end_date.date())
                ).order_by("-created")
            ]

dg_data = DgUnitConsumption.objects.filter(
                site=site_id,
                created__date__range=(from_date.date(), end_date.date())
            ).order_by('-created')

dg_fuel_unit_data = [
                {
                    "Start_Date": i.dg_start_date.strftime("%d-%b-%Y"),
                    "Start_Time": f"{i.dg_start_date.hour}:{i.dg_start_date.minute}",
                    "End_Date": i.dg_end_date.strftime("%d-%b-%Y"),
                    "End_Time": f"{i.dg_end_date.hour}:{i.dg_end_date.minute}",
                    "DG_Fuel_Consumed(Litres)": i.dg_fuel_consumption,
                    "DG_Unit_Consumption(KWH)": i.unit_consumption,
                    "DG_Unit_Per_Ltr": round(i.unit_consumption / i.dg_fuel_consumption, 2) if i.dg_fuel_consumption > 0 else 0,
                }
                for i in dg_data
            ]

alerts = DGAlertsData.objects.filter(
                Q(alert_data__contains=vehical_number),
                Q(created__date__range=(from_date.date(), end_date.date()))
            )
refuel_theft_data = [
                {
                    "Date": datetime.strptime(i.get('event_time', i.get('dateTimeStamp')[:-6]), "%Y-%m-%dT%H:%M:%S.%f").strftime("%d-%b-%Y"),
                    "Time": datetime.strptime(i.get('event_time', i.get('dateTimeStamp')[:-6]), "%Y-%m-%dT%H:%M:%S.%f").strftime("%H:%M"),
                    "Activity": "Refuel" if i.get('alert_type', i.get('eventType')) in ['RefuelingAlert', 'deviceFuelFill'] else "Theft",
                    "Fuel(in Litres)": round(float(i.get('refueled_in_liters', i.get('fuelChange').split('ltr')[0])), 2),
                }
                for i in [alert.alert_data for alert in alerts]
                if i.get('alert_type', i.get('eventType')) in ['RefuelingAlert', 'theft', 'deviceFuelDrop', 'deviceFuelFill']
            ]

current_date = datetime.now().strftime("%d-%B-%Y")
io_buffer = BytesIO()
with pd.ExcelWriter('dg_fuel_report.xlsx', engine='xlsxwriter') as writer:
    pd.DataFrame(fuel_absolute_data).to_excel(writer, sheet_name='Fuel Level', index=False)
    pd.DataFrame(dg_fuel_unit_data).to_excel(writer, sheet_name='DG Fuel & Unit Consumption', index=False)
    pd.DataFrame(refuel_theft_data).to_excel(writer, sheet_name='DG Refuel & Theft Data', index=False)

