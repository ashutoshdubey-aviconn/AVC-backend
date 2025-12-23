import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')
django.setup()
from django.db.models import F, Q
import datetime
from datetime import timedelta
from wareApp.models import *

def post():
        #data = request.data
        data = {"site_id" : 29, "from_date" : "2025/11/09", "till_date" : "2025/11/09", "user_type" : 0}
        site_id = int(data.get("site_id", 0))
        if site_id == 34:
            site_id = 29

        try:
            site = Site.objects.get(id=site_id)
            from_date = datetime.strptime(data.get("from_date", ""), "%Y/%m/%d")
            till_date = datetime.strptime(data.get("till_date", ""), "%Y/%m/%d")
            user_type = int(data.get("user_type", 0))
            print(from_date, till_date, user_type)
            total_days = (till_date - from_date).days + 1
            
            all_dates = [(till_date - timedelta(days=i)).date() for i in range(total_days)]
            all_dates.reverse()
            print(all_dates)

            filter_condition = (
                Q(attached_leg_id__in=[259, 260, 261, 276, 710])
                if int(data.get("site_id", 0)) == 34
                else Q(site_id=site_id)
            )

            # Add is_visible condition only if user_type is not 1 and the site is not 34
            if user_type != 1 and int(data.get("site_id", 0)) != 34:
                filter_condition &= ~Q(is_visible=False)

            aisle_group = AisleGroup.objects.filter(filter_condition)
            print(len(aisle_group))
            print(aisle_group)
            aisle_map = {aisle.attached_leg_id: aisle.aisleGroupName for aisle in aisle_group}
            all_leg_ids = list(aisle_map.keys())
            print(all_leg_ids)

            if from_date < site.live_date:
                from_date = site.live_date
            
            all_data = DailySiteReading.objects.filter(
                associated_Site=site, leg_id__in=all_leg_ids,
                reading_for__range=[from_date.date(), till_date.date()], is_visible=True
            ).values("leg_id", "reading_for", "unit_consumption")
            print(len(all_data))
            
            data_dict = {}
            for record in all_data:
                print(record)
                leg_id, reading_for, unit_consumption = record.values()
                aisle_name = aisle_map.get(leg_id, "Unknown")
                idx = all_dates.index(reading_for) if reading_for in all_dates else None
                if idx is not None:
                    data_dict.setdefault(aisle_name, [0] * total_days)[idx] = round(unit_consumption, 2)

            data_list = [{"name": k, "data": v, "type": "column"} for k, v in data_dict.items()]
            saving_data_list = data_list.copy()

            baseline_list = []
            if site.is_live:
                baseline_filter = Q(associated_site_id=site_id, leg_id__in=all_leg_ids)
                latest_baseline_values = SiteBaseline.objects.filter(baseline_filter)
                print(latest_baseline_values)
                
                for date in all_dates:
                    baseline_value = latest_baseline_values.filter(
                        Q(baseline_to__gte=date) | Q(Q(baseline_from__lte=date) & Q(baseline_to__isnull=True))
                    ).aggregate(Sum('baseline_value'))['baseline_value__sum'] or 0
                    baseline_list.append(round(baseline_value, 2))
                
                data_list.append({"name": "baseline", "data": baseline_list, "type": "spline"})
            
            #return Response({"result": 1, "Dates": all_dates, "Data": data_list, "SavingData": saving_data_list})
        
        except Exception as err:
            print(str(err))
            #return Response({"status": 500, "msg": str(err)})


post()
