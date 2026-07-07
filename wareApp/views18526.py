from django.shortcuts import render
from django.db.models import Sum, Avg, Max, Min, Count
from django.db.models import Case, CharField, Value, When
from django.contrib.auth.hashers import make_password
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User, Group
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate
#############################
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated, AllowAny
# Create your views here.
from wareApp.models import *
from wareApp import sendmail
from wareApp.serializers import *
from wareApp.utility import entryExit, logger
#################################
from datetime import timedelta, datetime, time
from telnetlib import STATUS
import time
from collections import defaultdict
from django.http import HttpResponse
import pandas as pd
from django.db.models import Q
from io import BytesIO
from django.db.models.functions import TruncMonth, TruncMinute


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    User = get_user_model()
    queryset = User.objects.all().order_by('-date_joined')
    # serializer_class = UserSerializer


class GroupViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """
    queryset = Group.objects.all()
    # serializer_class = GroupSerializer


# SuperUser Api Start From Here *************************************

class FetchAllCustomersForSuperAdmin(APIView):
    # authentication_classes = [TokenAuthentication]
    # permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        print("data", data)
        user_id = data.get('user_id')
        print("user_id", user_id)
        start_date = data.get("start_date")
        end_date = data.get('end_date')
        super_user = User.objects.get(id=user_id)
        print("super_user", super_user)
        all_users = User.objects.filter(UserType=4)
        print("all_users", all_users)
        response_data = []
        for users in all_users:
            print("users : ", users)
            customer_data = {}
            all_live_sites = Site.objects.filter(customer=users, is_live=True)
            print("all_live_sites", all_live_sites)
            total_sites = Site.objects.filter(customer=users).count()
            total_live_sites = all_live_sites.count()
            print("live_sites", total_live_sites)
            all_live_sites_id = [i.id for i in all_live_sites]
            if start_date is not None and end_date is not None:
                start_date = datetime.strptime(start_date, "%Y/%m/%d")
                print("start_date", start_date)
                end_date = datetime.strptime(end_date, "%Y/%m/%d")
                print("end_date", end_date)
                d = DailySiteReading.objects.values('reading_for').filter(associated_Site__in=all_live_sites_id,
                                                                          reading_for__gte=start_date,
                                                                          reading_for__lte=end_date).annotate(
                    leg_count=Count('leg_id'),
                    sum=Sum('energy_saved'),
                    baseline=Sum('daily_baseline_value'))
            else:
                current_date = datetime.now()
                d = DailySiteReading.objects.values('reading_for').filter(associated_Site__in=all_live_sites_id,
                                                                          reading_for__year=current_date.year,
                                                                          reading_for__month=current_date.month,
                                                                          ).annotate(
                    leg_count=Count('leg_id'),
                    sum=Sum('energy_saved'),
                    baseline=Sum('daily_baseline_value'))

            print("daily_reading", d)
            total_energy_saved = [i.get('sum') for i in d]
            print("toal_energy_saved : ", total_energy_saved)
            total_baseline = [i.get('baseline') for i in d]
            print("total_baseline : ", total_baseline)
            if sum(total_energy_saved) > 0 and sum(total_baseline) > 0:
                try:
                    average = (sum(total_energy_saved) / sum(total_baseline)) * 100
                    print("average value", average)
                    max_saving = (max(total_energy_saved) / (
                        total_baseline[total_energy_saved.index(max(total_energy_saved))])) * 100
                    min_saving = (min(total_energy_saved) / (
                        total_baseline[total_energy_saved.index(min(total_energy_saved))])) * 100
                except Exception as e:
                    print("exception is", e)
            else:
                average = 0
                max_saving = 0
                min_saving = 0
            customer_data['customer_id'] = users.id
            customer_data['customer_name'] = users.username
            customer_data['total_WH'] = total_sites
            customer_data['live_Wh'] = total_live_sites
            customer_data['avg_saving'] = str(round(average, 2)) + ' %'
            customer_data['max_saving'] = str(round(max_saving, 2)) + ' %'
            customer_data['min_saving'] = str(round(min_saving, 2)) + ' %'
            response_data.append(customer_data)
        return Response({"data": response_data})


class SuperAdminSnapShot(APIView):
    def post(self, request, *args):
        data = request.data
        print("data : ", data)
        user_id = data.get("user_id")
        start_date = data.get("start_date")
        # date = datetime.strptime(start_date, "%Y/%m/%d")
        # print("date ", date)
        end_date = data.get("end_date")
        current_date = datetime.now()
        previous_date = current_date.replace(day=1)
        date = previous_date.strftime("%Y/%m/%d")
        # enddate = datetime.strptime(end_date, "%Y/%m/%d")
        # print("end_date :",enddate)
        super_user = User.objects.get(id=user_id)
        print("super_user :", super_user)
        all_users = User.objects.filter(UserType=4)
        all_users_id = [i.id for i in all_users]
        print("all_user_id : ", all_users_id)
        all_live_sites = Site.objects.filter(customer__in=all_users_id, is_live=True)
        print("all_live_sites :", all_live_sites)
        all_live_sites_id = [i.id for i in all_live_sites]
        print("all live sites : ", all_live_sites_id)
        all_alarms = AlarmNotifications.objects.filter(site_id__in=all_live_sites_id, is_active=True).count()
        print(all_alarms)
        counter = 0
        total_percentage_saved = 0
        total_consumed_energy = 0
        total_saved_energy = 0
        for users in all_users:
            print("users : ", users)
            customer_data = {}
            all_live_sites = Site.objects.filter(customer=users, is_live=True)
            print("all_live_sites", all_live_sites)
            total_sites = Site.objects.filter(customer=users).count()
            total_live_sites = all_live_sites.count()
            print("live_sites", total_live_sites)
            all_live_sites_id = [i.id for i in all_live_sites]
            if start_date is not None and end_date is not None:
                start_date = datetime.strptime(start_date, "%Y/%m/%d")
                print("start_date", start_date)
                end_date = datetime.strptime(end_date, "%Y/%m/%d")
                print("end_date", end_date)
                d = DailySiteReading.objects.values('reading_for').filter(associated_Site__in=all_live_sites_id,
                                                                          reading_for__gte=start_date,
                                                                          reading_for__lte=end_date).annotate(
                    leg_count=Count('leg_id'),
                    sum=Sum('energy_saved'),
                    baseline=Sum('daily_baseline_value'))
                print("d", d)
            else:
                current_date = datetime.now()
                d = DailySiteReading.objects.filter(associated_Site__in=all_live_sites_id,
                                                    reading_for__year=current_date.year,
                                                    reading_for__month=current_date.month,
                                                    ).aggregate(
                    total_energy_saved=Sum('energy_saved'),
                    total_baseline=Sum('daily_baseline_value'),
                    total_unit_consumed=Sum('unit_consumption'))
                print("output : ", d)
            if d.get('total_energy_saved') is not None and d.get('total_energy_saved') > 0 and d.get(
                    'total_baseline') is not None and d.get('total_baseline') > 0:
                counter += 1
                total_percentage_saved += (d.get('total_energy_saved') / d.get('total_baseline')) * 100
                print("total_percentage_saved", total_percentage_saved)
                total_consumed_energy += (d.get('total_unit_consumed'))
                print("total_consumed_energy", total_consumed_energy)
                total_saved_energy += (d.get('total_energy_saved'))
                print("total_saved_energy", total_saved_energy)

        return Response(
            {"current_date": date, "alarms": all_alarms, "total_unit_consumed": round(total_consumed_energy, 2),
             "total_energy_saved": round(total_saved_energy, 2),
             "total_saved_percentage": str(round(total_percentage_saved, 2))})


class SuperUserAllAlarmsPriorityBasedOnCustomersList(APIView):
    def post(self, request):
        data = request.data
        print("request data : ", data)
        user_id = data.get('id')
        all_customers = User.objects.filter(UserType=4)
        response_data = []
        for customer in all_customers:
            print("customers :", customer)
            customer_data = {}
            all_sites = Site.objects.filter(customer=customer, is_live=True)
            print("all_sites :", all_sites)
            all_sites_id = [i.id for i in all_sites]
            print("all_sites_id :", all_sites_id)
            alarms = AlarmNotifications.objects.values('Alarm_priority', 'site_id__site_name').filter(
                site_id__in=all_sites_id,
                is_active=True).annotate(
                alarm_count=Count('id'))

            print("alarm : ", alarms)
            customer_data['customer_id'] = customer.id
            customer_data['customer_name'] = customer.username
            customer_data['alarm_list'] = alarms
            response_data.append(alarms)
        return Response({"data": response_data})


class SuperUserAllAlarmsTypeBasedOnCustomersList(APIView):
    def post(self, request):
        data = request.data
        print("data : ", data)
        user_id = data.get('user_id')
        all_customers = User.objects.filter(UserType=4)
        response_data = []
        for customer in all_customers:
            customer_data = {}
            all_sites = Site.objects.filter(customer=customer, is_live=True)
            print(all_sites)
            all_sites_id = [i.id for i in all_sites]
            choices = dict(AlarmNotifications._meta.get_field('Alarm_type').flatchoices)
            whens = [When(Alarm_type=k, then=Value(v)) for k, v in choices.items()]
            alarms = AlarmNotifications.objects.filter(site_id__in=all_sites_id,
                                                       is_active=True).annotate(
                alarm_count=Count('id'),
                alarm=Case(*whens, output_field=CharField())

            ).values('alarm', 'Alarm_priority', 'site_id__site_name', 'created_time')
            if alarms:
                customer_data['customer_id'] = customer.id
                customer_data['customer_name'] = customer.username
                customer_data['alarm_list'] = alarms
                response_data.append(customer_data)
        return Response({"data": response_data})


# SuperUser Api Ends Here ******************************

# class SiteTotalGraphDataDaily(APIView):

#     def post(self, request):
#         data = request.data
#         till_date = data.get("till_date", "")
#         from_date = data.get("from_date", "")
#         print("from date: ", from_date)
#         site_id = data.get("site_id", " ")
#         print("This is the site id: ", site_id)
#         site = Site.objects.get(id=int(site_id))
#         print("site: ", site)
#         try:
#             from_date = datetime.strptime(from_date, '%Y/%m/%d')
#             till_date = datetime.strptime(till_date, '%Y/%m/%d')
#             data = []
#             dates = []
#             print("distinct legs")
#             for leg in DailySiteReading.objects.distinct('leg_id').filter(associated_Site=int(site_id)):
#                 daily_consumption = []
#                 dates = []
#                 print("limits")
#                 dateLowerLimitCheck = from_date.date()
#                 dateUpperLimitCheck = till_date.date()
#                 print("dateUpperLimitCheck", dateUpperLimitCheck)
#                 given_date_graph_data = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg,
#                                                                         reading_for__gte=dateLowerLimitCheck,
#                                                                         reading_for__lte=dateUpperLimitCheck)
#                 date = from_date.date()
#                 print("LOOP!!")
#                 for i in range(31):
#                     if date <= till_date.date():
#                         dates.append(date)
#                         print(date)
#                         if given_date_graph_data.filter(reading_for=date).exists():
#                             one_day_consumption = round(
#                                 given_date_graph_data.filter(reading_for=date)[0].unit_consumption, 2)
#                         else:
#                             one_day_consumption = 0
#                         daily_consumption.append(one_day_consumption)

#                     else:
#                         break

#                     if AisleGroup.objects.filter(attached_leg_id=leg).exists():
#                         aisle_group = AisleGroup.objects.get(attached_leg_id=leg).aisleGroupName
#                     else:
#                         aisle_group = str(leg)
#                     date = date + timedelta(days=1)
#                 # aisle_name = leg.leg_id
#                 # if aisle_name == "1848":
#                 #    name="MAINS SUPPLY"
#                 # elif aisle_name == "1849":
#                 #    name = "DG 1"

#                 singleData = {"name": aisle_group, "data": daily_consumption}
#                 data.append(singleData)

#             response = {
#                 'Dates': dates,
#                 'Data': data,
#                 'status': '1',
#                 'msg': 'Data Present'
#             }
#             print("response :", response)

#             return Response(response)

#         except Exception as e:
#             print('exception is ', e)
#             return Response({"error": "errorrrrrrrrrrrrrrrrr"})

class SiteTotalGraphDataDaily(APIView):

    def post(self, request):
        from django.core.cache import cache
        data = request.data
        till_date = data.get("till_date", "")
        from_date = data.get("from_date", "")
        print("from date: ", from_date)
        site_id = data.get("site_id", " ")
        print("This is the site id: ", site_id)
        site = Site.objects.get(id=int(site_id))
        print("site: ", site)
        try:
            from_date = datetime.strptime(from_date, '%Y/%m/%d')
            till_date = datetime.strptime(till_date, '%Y/%m/%d')
            
            # Optimization & Caching START
            data = []
            
            # 1. Calculate Date Range (Caps at 31 days)
            max_days = 31
            actual_days = (till_date - from_date).days + 1
            days_to_process = min(actual_days, max_days)
            
            dates_obj_list = [from_date.date() + timedelta(days=i) for i in range(days_to_process)]
            dates = dates_obj_list # for response
            
            if not dates_obj_list:
                return Response({'Dates': [], 'Data': [], 'status': '1', 'msg': 'No Data'})

            start_date_obj = dates_obj_list[0]
            end_date_obj = dates_obj_list[-1]
            
            # 2. Fetch all unique legs for the site (to preserve list of series even if empty)
            legs = DailySiteReading.objects.filter(associated_Site=site).values_list('leg_id', flat=True).distinct()
            
            # 3. Fetch Readings with Monthly Caching Strategy
            readings_map = defaultdict(dict)
            current_date = datetime.now().date()
            
            # Helper to generate month ranges
            month_ranges = []
            curr = start_date_obj
            while curr <= end_date_obj:
                # End of current month
                if curr.month == 12:
                    next_month = curr.replace(year=curr.year + 1, month=1, day=1)
                else:
                    next_month = curr.replace(month=curr.month + 1, day=1)
                
                month_end = next_month - timedelta(days=1)
                segment_end = min(month_end, end_date_obj)
                
                month_ranges.append((curr, segment_end))
                curr = next_month

            for m_start, m_end in month_ranges:
                is_past_month = (m_start.year < current_date.year) or (m_start.year == current_date.year and m_start.month < current_date.month)
                
                if is_past_month:
                    cache_key = f"SITE_{site.id}_DAILY_READINGS_V1_{m_start.year}_{m_start.month}"
                    #cached_month_data = cache.get(cache_key)
                    cached_month_data=None
                    
                    if cached_month_data is None:
                        # Fetch entire month data for cache consistency
                        full_month_start = m_start.replace(day=1)
                        if full_month_start.month == 12:
                            full_month_next = full_month_start.replace(year=full_month_start.year + 1, month=1, day=1)
                        else:
                            full_month_next = full_month_start.replace(month=full_month_start.month + 1, day=1)
                        full_month_end = full_month_next - timedelta(days=1)
                        
                        month_readings = DailySiteReading.objects.filter(
                            associated_Site=site,
                            reading_for__range=[full_month_start, full_month_end]
                        ).values('leg_id', 'reading_for', 'unit_consumption')
                        
                        cached_month_data = defaultdict(dict)
                        for r in month_readings:
                            cached_month_data[r['leg_id']][r['reading_for']] = r['unit_consumption']
                        
                        # Cache for 24 hours (86400 seconds)
                        #cache.set(cache_key, cached_month_data, timeout=86400)
                    
                    # Merge cached data relevant to requested range into main map
                    for leg, dates_data in cached_month_data.items():
                        for d_key, val in dates_data.items():
                            if m_start <= d_key <= m_end:
                                readings_map[leg][d_key] = val

                else:
                    # Current/Future month: Fetch fresh (only requested range to be efficient)
                    fresh_readings = DailySiteReading.objects.filter(
                        associated_Site=site,
                        reading_for__range=[m_start, m_end]
                    ).values('leg_id', 'reading_for', 'unit_consumption')
                    
                    for r in fresh_readings:
                        readings_map[r['leg_id']][r['reading_for']] = r['unit_consumption']
            
            # 4. Bulk fetch AisleGroup Names
            name_map = {}
            try:
                aisle_groups = AisleGroup.objects.filter(attached_leg_id__in=legs).values('attached_leg_id', 'aisleGroupName')
                name_map = {item['attached_leg_id']: item['aisleGroupName'] for item in aisle_groups}
            except Exception as e:
                print("Error calculating names:", e)

            # 5. Construct Data
            for leg_id in legs:
                daily_consumption = []
                for d in dates_obj_list:
                    # Get consumption from map, default to 0
                    val = readings_map.get(leg_id, {}).get(d, 0)
                    daily_consumption.append(round(val, 2))
                
                # Get name from map, default to leg_id
                aisle_group_name = name_map.get(leg_id, str(leg_id))
                
                singleData = {"name": aisle_group_name, "data": daily_consumption}
                data.append(singleData)

            response = {
                'Dates': dates,
                'Data': data,
                'status': '1',
                'msg': 'Data Present'
            }
            print("response :", response)

            return Response(response)

        except Exception as e:
            print('exception is ', e)
            import traceback
            traceback.print_exc()
            return Response({"error": str(e)})


class SiteTotalGraphDataHourly(APIView):

    def post(self, request):
        data = request.data
        date = data.get("date", "")
        print("input date: ", date)
        date = datetime.strptime(date, "%Y/%m/%d")
        site_id = data.get("site_id", " ")
        print("This is the site id: ", site_id)
        site = Site.objects.get(id=site_id)
        print("site: ", site)
        try:
            data = []
            hours = []
            for leg in DailySiteReading.objects.distinct('leg_id').filter(associated_Site=site):
                print("leg id is:", leg)
                hourly_consumption = []
                hours = []

                for i in range(24):
                    hr = date.hour + i
                    if hr <= 9:
                        hr = "0" + str(hr) + ":00"
                    else:
                        hr = str(hr) + ":00"
                    hours.append(hr)
                    hour = date.replace(hour=i)
                    print("hour :", hour)
                    hours_graph_data = HourlySiteReading.objects.filter(associated_Site=site, leg_id=leg,
                                                                        reading_from=hour)
                    print("hours_graph_data", hours_graph_data)
                    if hours_graph_data.exists():
                        one_hour_consumption = round(hours_graph_data[0].unit_consumption, 2)
                        print("one_hour_consumption", one_hour_consumption)
                    else:
                        one_hour_consumption = 0.0
                    hourly_consumption.append(one_hour_consumption)
                if AisleGroup.objects.filter(attached_leg_id=leg).exists():
                    aisle_group = AisleGroup.objects.get(attached_leg_id=leg).aisleGroupName
                else:
                    aisle_group = str(leg)
                singleData = {"name": aisle_group, "data": hourly_consumption}
                data.append(singleData)

            response = {
                'Hours': hours,
                'Data': data,
                'status': '1',
                'msg': 'Data Present'
            }
            print("response :", response)

            return Response(response)

        except Exception as e:
            print('exception is ', e)
            return Response({"error": "errorrrrrrrrrrrrrrrrr"})




class SiteTotalGraphDataHourlyWHTM(APIView):
    def post(self, request):
        data = request.data
        date , site_id = data.get("date", ""), data.get("site_id", "")
        date = datetime.strptime(date, "%Y/%m/%d")
        try:
            hourlyData , hours = [] , ["{:02d}:00".format(i) for i in range(24)]
            rooms = list(reversed(list(AisleGroup.objects.filter(site=site_id).values_list('attached_leg_id', flat=True))))
            for i in rooms:
                cons = list(
                    HourlySiteReading.objects.filter(associated_Site=site_id, leg_id=i, reading_from__date=date).order_by('reading_from__hour').values_list('unit_consumption', flat=True)
                )
                cons.extend([0]*(24-len(cons)))
                hourlyData.append(
                    {
                        'name' : AisleGroup.objects.get(attached_leg_id=i).aisleGroupName if AisleGroup.objects.filter(attached_leg_id=i).exists() else i,
                        'data' : [round(j, 2) for j in cons]
                    }
                )
            return Response({"status": 1, "Hours": hours, "Data": hourlyData, 'msg': 'Data Present'})
            
        except Exception as e:
            return Response({"error": e.args, "status": 0, 'msg': 'Data Not Present'})





class DgFuelConsumptionDataApi_new(APIView):
    '''
    This API is used to get the DG fuel consumption data for a site on a given date. Uses the Loconav Push API for the process.
    '''
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        print("data: ", data)
        try:
            site_id = data.get("site_id")
            date = data.get("date")
            site = Site.objects.get(id=site_id)
            selected_date = datetime.strptime(date, "%Y/%m/%d")
            vehical_number = site.partner_dg_fuel_id.upper()
            print(selected_date)
            date = date.replace('/', '-')
            print(date)
            final_data = []
            fuel_data = DgFuelConsumptionData.objects.filter(site=site_id, created__date=selected_date.date()).order_by(
                "created")
            for i in fuel_data:
                final_data.append({"x": int(i.epoch_time), "y": round(i.fuel_consumption, 2)})
            dg_data = DgUnitConsumption.objects.filter(site=site_id, created__date=selected_date.date())
            logger.debug(final_data)
            logger.debug(dg_data)
            print("dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: ", i)
                    dg_unit_data.append({"x": int(i.epoch_time), "y": round(i.unit_consumption, 2)})
                    if i.dg_fuel_consumption > 0:
                        dg_fuel_data.append({"x": int(i.epoch_time), "y": i.dg_fuel_consumption})
                        dg_unit_per_litre.append(
                            {"x": int(i.epoch_time), "y": round(i.unit_consumption / i.dg_fuel_consumption, 2)})
            else:
                print('inside else')
                dg_unit_data = []
                dg_fuel_data = []
                dg_unit_per_litre = []
            fuel_alerts = DGAlertsData.objects.all()
            refuel_data = []
            theft_data = []

            print(vehical_number)
            refuel_alerts_for_site = DGAlertsData.objects.filter(
                Q(alert_data__contains = vehical_number) &
                Q(alert_data__contains = 'RefuelingAlert') &
                Q(created__date = selected_date.date())
            )
            print(selected_date)
            print(len(refuel_alerts_for_site))
            refueling_alerts = [i.alert_data for i in refuel_alerts_for_site]
            for i in refueling_alerts:
                print(i)
                epoch_time = datetime.strptime(i.get('event_time')[:-6], "%Y-%m-%dT%H:%M:%S.%f").timestamp()
                refuel_data.append({'x': int(epoch_time) * 1000, 'y': i.get('refueled_in_liters')})

            theft_alerts = DGAlertsData.objects.filter(
                Q(alert_data__contains = vehical_number) &
                Q(alert_data__contains = 'theft') &
                Q(created__date = selected_date.date()) 
            )
            theft_alerts = [i.alert_data for i in theft_alerts]
            for i in theft_alerts:
                theft_data.append({'x': i.timestamp * 1000, 'y': i.get('value')})
            
            refuel_final_data = {"name": "Refuel", "data": refuel_data, "type": "column"}
            theft_final_data = {"name": "Fuel Drain", "data": theft_data, "type": "column"}
            dg_unit_final_data = {"name": "DG_Unit_Consumption", "data": dg_unit_data, "type": "column"}
            dg_fuel_final_data = {"name": "DG_Fuel_Consumed", "data": dg_fuel_data, "type": "column"}
            dg_unit_per_litre_data = {"name": "Dg_Unit_Per_Ltr", "data": dg_unit_per_litre, "type": "column"}
            return Response(
                {"status": 200, "data": final_data, "refuel_alert": refuel_final_data, "theft_alert": theft_final_data,
                 "dg_unit_data": dg_unit_final_data, "dg_fuel_data": dg_fuel_final_data,
                 "dg_unit_per_litre_data": dg_unit_per_litre_data, "sample":"false"})
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})



class SubmeteringMonthlyBarChart_new(APIView):
    permission_classes = [AllowAny]
    @entryExit
    def post(self,request):
        try:
        # Extracting the data from the request
            data = request.data
            site_id, from_date, till_date, user_type = data.get("site_id", ""), data.get("from_date", ""), data.get("till_date", ""), data.get("user_type", "")

            # Extracting the Daily Data for the given Date Range
            from_date = datetime.strptime(from_date, "%Y/%m/%d")
            till_date = datetime.strptime(till_date, "%Y/%m/%d")

            dates = [(from_date + timedelta(days=x)).strftime("%Y-%m-%d") for x in range((till_date - from_date).days + 1)]
            dataList = []
            site = Site.objects.get(id=site_id)
            if from_date < site.live_date.replace(tzinfo=None):
                from_date = site.live_date

            # Extracting the Site Data and the Available Rooms
            rooms = AisleGroup.objects.filter(site=site_id).values_list('id', 'aisleGroupName')

            # Extracting the Data for the given Date Range
            for room in rooms:
                Dailydata = DailySiteReading.objects.filter(associated_Site=site, leg_id=room[0], reading_for__range=[from_date, till_date], is_visible=True).order_by('reading_for')
                Dailydata = Dailydata.values_list('reading_for','unit_consumption')
                if Dailydata.exists:
                    DailydataDict = dict(Dailydata)
                    new_list = [round(DailydataDict.get(datetime.strptime(d, "%Y-%m-%d").date(), 0),2) for d in dates]
                    dataList.append({"name": room[1], "data": new_list, "type": "column"})
                else:
                    Dailydata = [0] * len(dates)
                    dataList.append({"name": room[1], "data": Dailydata, "type": "column"})

            # Returning the Response
            return Response({"status": 200, "Dates": dates, "Data": dataList}, status=200)

        except Exception as err:
            return Response({"status": 500, "msg": str(err)}, status=500)




class SiteCurrentLoadInfo(APIView):

    def post(self, request):

        data = request.data
        site_id = data.get("site_id")
        load_value = r_current = y_current = b_current = 0
        r_volt = y_volt = b_volt = max_load = min_load = 0
        r_power_factor = y_power_factor = b_power_factor = 0.0
        power_supply = status = ''

        # print(site_id)
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            active_power_sources = SiteLoadPower.objects.filter(Associated_Site=int(site_id), Status='ON')
            for i in active_power_sources:
                power_load = i.Site_Total_Load
                power_load = power_load / 1000
                value = power_load
                load_value += value

                r_volt = int(round(i.r_volt, 0))
                y_volt = int(round(i.y_volt, 0))
                b_volt = int(round(i.b_volt, 0))
                r_current += int(i.r_current)
                y_current += int(i.y_current)
                b_current += int(i.b_current)
                r_power_factor = (i.r_power_factor)
                y_power_factor = (i.y_power_factor)
                b_power_factor = (i.b_power_factor)
                max_load = round(i.max_load / 1000, 3)
                min_load = round(i.min_load / 1000, 3)
                power_supply = i.Supply_Source
                status = i.Status

            return Response(
                {"Total_Load": str(round(load_value, 3)), 'R_Voltage': str(r_volt), 'Y_Voltage': str(y_volt),
                 'B_Voltage': str(b_volt), 'R_Current': str(round(r_current, 0)), 'Y_Current': str(round(y_current, 0)),
                 'B_Current': str(round(b_current, 0)), 'R_Power_Factor': str(round(r_power_factor, 3)),
                 'Y_Power_Factor': str(round(y_power_factor, 3)), 'B_Power_Factor': str(round(b_power_factor, 3)),
                 'max_load': str(max_load), 'min_load': str(min_load),
                 "Power_supply": power_supply, "Status": status})

        except Exception as e:
            print("This is exception ", e)
            return Response({"status": 500, "error": "ERROR", "msg": str(e)})


class SitePhaseVoltagesInfo(APIView):

    def post(self, request, *args, **kwargs):
        data = request.data
        site_id = data.get("site_id")
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            if True:  # Token.objects.filter(key=token_key) :
                r_volt = InstantenousPhaseVoltage.objects.filter(Assocted_Site=int(site_id))[0].r_volt
                y_volt = InstantenousPhaseVoltage.objects.filter(Assocaited_Site=int(site_id))[0].y_volt
                b_volt = InstantenousPhaseVoltage.objects.filter(Assocaited_Site=int(site_id))[0].b_volt
                return Response(
                    {'R-phase Voltage': str(r_volt), 'Y-phase Voltage': str(y_volt), 'B-phase Voltage': str(b_volt)})

            else:
                print("This session key is not valid.")
                return Response({"Error": "This session key is not valid."})

        except Exception as e:
            print("This is exception ", e)
            return Response({"Error": "EXCEPTION"})


class SitePhaseCurrentsInfo(APIView):

    def post(self, request, *args, **kwargs):
        data = request.data
        site_id = data.get("site_id")
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            if True:  # Token.objects.filter(key=token_key) :
                r_current = InstantenousPhaseCurrent.objects.filter(Assocaited_Site=int(site_id))[0].r_current
                y_current = InstantenousPhaseCurrent.objects.filter(Assocaited_Site=int(site_id))[0].y_current
                b_current = InstantenousPhaseCurrent.objects.filter(Assocaited_Site=int(site_id))[0].b_current
                return Response(
                    {'R-phase Current': str(r_current), 'Y-phase Current': str(y_current),
                     'B-phase Current': str(b_current)})

            else:
                print("This session key is not valid.")

        except Exception as e:
            print("This is exception ", e)


class PowerSupplyInfo(APIView):

    def post(self):
        data = self.request
        site_id = data.site_id("site_id", )
        # token_key = request.META.get('HTTP_AUTHORIZATION')
        # token_key = token_key[6:]
        # print("This is the token value: ", token_key)
        try:
            if True:  # Token.objects.filter(key=token_key) :
                power_supply = PowerSupplyStatus.objects.filter(Associated_Site=site_id)[0].Supply_Source
                return Response({"Power_supply": power_supply})

            else:
                print("This session key is not valid.")

        except Exception as e:
            print("This is exception ", e)


from rest_framework.throttling import AnonRateThrottle


class LoginApi(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    @entryExit
    def post(self, request):
        logger.debug(request.data)
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, created = Token.objects.get_or_create(user=user)
        userinfo = User.objects.get(id=token.user_id)
        serializer_class = UserSerializer(userinfo, many=False)
        return Response({"token": token.key, "user": serializer_class.data})


class ValidatedToken(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        logger.debug(request.data)
        data = request.data
        token = data.get("token", '')
        if token:
            user = Token.objects.filter(key=token)
            if user:
                return Response({"result": "true"})
            else:
                return Response({"result": "false"})
        else:
            return Response({"error": "invalid API Payload"}, status=status.HTTP_400_BAD_REQUEST)


class TokenViewSet(viewsets.ModelViewSet):
    pass
    # queryset = Token.objects.all()
    # serializer_class = TokenSerializer


class ForgetPassword(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        print("data : ", data)
        username = data.get("Username", "")
        print("username : ", username)
        email = data.get("email", "")
        contact_number = data.get("mobile", "")
        try:
            if User.objects.filter(username=username):
                print("inside if")
                user = User.objects.get(username=username)
                print("user : ", user)
                if str(user.email) == str(email) and str(user.Contact_number) == str(contact_number):
                    print("###")
                    otp = sendmail.emailcheck(user.id, user.username, user.email)
                    return Response(
                        {"result": 1, "msg": "Otp sent successfull . Kindly check your email ", "otp": otp})
                else:
                    return Response({"result": 0, "msg": "Data is not valid"})
            else:
                return Response({"result": 0, "msg": "Username doesn't match in database"})
        except Exception as err:
            return Response({"result": 0, "msg": "Error!!!!!!!!!", "error": err})


class ResetPasswordApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        otp = str(data.get("otp", ""))
        new_password = data.get("newpassword", "")
        try:
            ide = OTP.objects.get(otp=otp).user_id
            user = User.objects.get(id=ide)
            user.set_password(new_password)
            user.save()
            return Response({"result": 1, "msg": "password reset successfully"})
        except OTP.DoesNotExist:
            logger.error("OTP:{otp} is not available")
            return Response({"result": 0, "msg": "OTP doesn't match"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as err:
            logger.critical(err)
            return Response({"result": 0, "msg": "API Error"}, status=status.HTTP_400_BAD_REQUEST)


class ChangePassword(APIView):
    permission_classes = [IsAuthenticated]

    @entryExit
    def post(self, request):
        data = request.data
        old_password = base64.b64decode(data.get("old_password", ''))  # Need to ask
        new_password = base64.b64decode(data.get("new_password", ""))  # Need to ask
        token = Token.objects.get(user=request.user)
        if authenticate(username=request.user.username, password=old_password):
            request.user.set_password(new_password)
            request.user.save()
            return Response({"result": 1, "msg": "Password changed successfully"})
        else:
            return Response({"result": 0, "msg": "Invalid old password"}, status=status.HTTP_400_BAD_REQUEST)


class CustomerView(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request, *args):
        customer = CustomerInfo.objects.all()
        logger.debug(customer)
        customer_serializer = CustomerInfoSerializer(customer, many=True)
        logger.debug(customer)
        return Response({"data": customer_serializer.data})


# token authentication used
class SiteInfo(APIView):
    @entryExit
    def get(self, request):  # post method should be used
        data = request.data
        site_id = data.get("siteId", '')
        site = Site.objects.get(Customer=site_id)
        serializer_class = SiteSerializer(site)
        return Response(serializer_class.data)


class CustomerTotalConsumption(APIView):
    @entryExit
    def post(self, request, *args):
        data = request.data
        print("data", data)
        customer_id = data["id"]
        print("customer id", customer_id, "id type", type(int(customer_id)))
        # customer_id = 2
        customerAllSites = Site.objects.filter(Customer=customer_id).order_by("id")  # no of sites for that customer
        print(customerAllSites)
        alarm = 0
        current_date = datetime.now()
        start_date = "18 August 2019"  # hardcoded date, should be replaced
        start_date = datetime.strptime(start_date, "%d %B %Y")
        print(start_date)
        date = abs(current_date.day - start_date.day)
        print(date)
        baseline_reading = 80  # hardcoded for the time been to be replaced when actual baseline is available
        # earlier_consumption_per_day = baseline_reading/30
        # total_readings = earlier_consumption_per_day * date
        total_readings = baseline_reading * date
        print(total_readings)
        total_consumption = 0.0
        for i in customerAllSites:
            hourlySiteReading = HourlySiteReading.objects.filter(associated_site_id=i.id)
            for j in hourlySiteReading:
                total_consumption += j.unit_consumption
        total_consumption = round(total_consumption, 2)
        print(total_consumption)
        total_energy_savings = (total_readings - total_consumption)
        total_energy_savings = round(total_energy_savings, 2)
        total_percentage_savings = round((total_energy_savings / total_readings) * 100, 2)
        return Response({"alarms": alarm, "totalConsumption": total_consumption,
                         "totalEnergySavings": total_energy_savings,
                         "totalPercentageSavings": total_percentage_savings})


class CustomerMonthlyGraphicalData(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print(data)
        customerId = data.get("id", "")
        print(customerId)
        customerAllSites = Site.objects.filter(customer=customerId).order_by("id")
        print(customerAllSites)
        currentMonth = datetime.now().date().month
        date = datetime.now().date()
        print("year", date)
        print(currentMonth)
        totalData = []
        dateList = []

        for i in range(12):
            print("i:", i)
            d = date - timedelta(i * 365 / 12)
            dates = d.replace(day=1)
            print("date", dates)
            total_consumption = 0.0
            for site in customerAllSites:
                print("site:", site)
                hourlySiteReading = HourlySiteReading.objects.filter(associated_site_id=site.id,
                                                                     reading_from__date__month=currentMonth - i)
                print("hsr:", hourlySiteReading)
                for j in hourlySiteReading:
                    print("j:", j)
                    print("date", j.reading_from)
                    total_consumption += j.unit_consumption
            print("total consumption:", total_consumption)
            totalData.append(total_consumption)
            dateList.append(dates)
        print("total data", totalData)
        return Response({"data": totalData, "date": dateList})


# class ParticularCustomerInfo(APIView):
#    def get(self, request):
#        token = request.META.get('HTTP_AUTHORIZATION')
#        token = token[6:]
#       print(token)
#       user_id = Token.objects.get(key=token).user_id
#       print(user_id)
#       user = User.objects.get(id=user_id).id
#       customer = CustomerInfo.objects.get(customer=user)
#       serializer = CustomerInfoSerializer(customer)
#       return Response({"result": 1, "data": serializer.data})


'''class CustomerAllSiteInfo(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        user_id = data.get("id", "")
        if user_id is None:
            token = request.META.get('HTTP_AUTHORIZATION')
            token = token[6:]
            print(token)
            customer_id = Token.objects.get(key=token).user_id
        else:
            customer_id = User.objects.get(id=int(user_id))
        sites = Site.objects.filter(customer=customer_id).order_by("id")
        serializer = SiteSerializer(sites, many=True)
        # print(serializer)
        return Response({"result": 1, "site": serializer.data})'''


class CustomerAllSiteInfo(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        user_id = data.get("id", "")
        if user_id is None:
            token = request.META.get('HTTP_AUTHORIZATION')
            token = token[6:]
            print(token)
            customer_id = Token.objects.get(key=token).user_id
        else:
            customer_id = User.objects.get(id=int(user_id))
        try:
            if customer_id and customer_id.UserType == 5:
                print("site manager admin")
                sites = CustomerSiteManager.objects.get(customer=customer_id)
                sites = sites.associated_site.all()
                serializer = SiteSerializer(sites, many=True)
                # print(serializer)
                return Response({"result": 1, "site": serializer.data, "msg": "site manager"})
            else:
                sites = Site.objects.filter(customer=customer_id).order_by("id")
                serializer = SiteSerializer(sites, many=True)
                # print(serializer)
                return Response({"result": 1, "site": serializer.data})
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class SiteInfo(APIView):
    @csrf_exempt
    @entryExit
    def post(self, request):  # post method should be used
        data = request.data
        print("This is the site data", data)
        id = data['siteId']
        site = Site.objects.get(id=id)
        serializer_class = SiteSerializer(site)
        return Response({"site": serializer_class.data})


'''class PowerDistributionPieChart(APIView):
    def post(self, request):
        data = request.data
        print("data :", data)
        site_id = data.get("siteId", '')
        current_date = datetime.now()
        dataList = []
        for power_source in SupplyLoadTimeShare.objects.distinct('power_source').order_by('power_source').filter(site=site_id):
            print("inside first for loop")
            graph = SupplyLoadTimeShare.objects.filter(site=site_id, power_source=power_source.power_source,
                                                       reading_from__year=current_date.year,
                                                       reading_from__month=current_date.month)
            print("graph data", graph)
            run_time = 0.0
            if graph.exists():
                for i in graph:
                    run_time += i.hourly_run_time
            power_source = power_source.get_power_source_display()
            dataList.append({"name": power_source, "data": run_time})
        print("data", dataList)
        date = current_date.strftime("%b-%Y")
        return Response({"result": 1, "data": dataList, "current_month": date})'''


class PowerDistributionPieChart(APIView):

    @entryExit
    def post(self, request):
        data = request.data
        data = request.data
        print("data :", data)
        site_id = data.get("siteId", '')
        current_date = datetime.now()
        dataList = []
        total = 0.0
        for leg in DailySiteReading.objects.distinct('leg_id').filter(associated_Site=int(site_id)):
            print("inside first for loop")
            graph = DailySiteReading.objects.filter(associated_Site=site_id, leg_id=leg,
                                                    reading_for__year=current_date.year,
                                                    reading_for__month=current_date.month)
            print("graph data", graph)
            unit_consumption = 0.0
            datapercentage = []

            if graph.exists():
                for i in graph:
                    unit_consumption += i.unit_consumption
                    print("unit_consumption :", unit_consumption)
            if AisleGroup.objects.filter(attached_leg_id=leg).exists():
                aisle_group = AisleGroup.objects.get(attached_leg_id=leg).aisleGroupName
            else:
                aisle_group = str(leg)

            dataList.append({"name": aisle_group, "data": unit_consumption})
        print("data", dataList)
        date = current_date.strftime("%b-%Y")
        finalData = []
        total_sum = sum([i['data'] for i in dataList])
        for i in dataList:
            try:
                percentage = i['data'] * 100 / total_sum
            except Exception:
                percentage = 0
            finalData.append({"name": i["name"], "data": round(percentage, 2)})
        return Response({"result": 1, "data": finalData, "current_month": date})


class HourlySiteReadingForOneSite(APIView):

    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get('site_id', '')
        print("siteId", site_id, type(site_id))
        site = Site.objects.get(id=int(site_id))
        date = data.get('date', '')
        print('received date', date)
        date_now = datetime.strptime(date, "%Y/%m/%d")
        print('converted date in date format', date_now)
        totalData = []
        all_leg_id = HourlySiteReading.objects.distinct('leg_id').filter(associated_Site=site)
        print('all leg id object', all_leg_id)
        for i in all_leg_id:
            oneLegDataList = []
            for j in range(0, 23):
                unit_consumption = 0.0
                hour = date_now + timedelta(hours=j)
                print("hour : ", hour.hour)
                hourly = HourlySiteReading.objects.filter(associated_Site=site,
                                                          leg_id=i.leg_id,
                                                          reading_from__date=date_now.date(),
                                                          reading_from__hour=hour.hour)

                for k in hourly:
                    unit_consumption += k.unit_consumption
                print('hour is :', hour, 'consumption of this hour is : ', unit_consumption)
                oneLegDataList.append({"hour": hour.hour, "consumption": unit_consumption})
            totalData.append({'legId': i.leg_id, "legData": oneLegDataList})
        return Response({'result': 1, 'data': totalData})


class PowerSourceDistributionMonthlyBarChartTime(APIView):
    def post(self, request):
        data = request.data
        print("request data :", data)
        site_id = data.get("site_id", '')
        from_date = data.get("from_date", '')
        till_date = data.get("till_date", '')
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        print("fromDate : ", fromDate, " tillDate: ", tillDate)
        currentDate = datetime.now()
        print("currentDate: ", currentDate)
        dateList = []
        dataList = []
        if tillDate.month == currentDate.month:
            print("###### inside current month  ######")
            for power_source in SupplyLoadTimeShare.objects.distinct('power_source').order_by('power_source').filter(
                    site=site_id):
                print("power source", power_source)
                dateList = []
                day_data_list = []
                for i in range(30):
                    date = tillDate.date() - timedelta(days=29 - i)
                    dateList.append(date)
                    print("date : ", date)
                    graph = SupplyLoadTimeShare.objects.filter(site=site_id, power_source=power_source.power_source,
                                                               reading_from__date=date)
                    print("all graph object :", graph)
                    run_time = 0.0
                    if graph.exists():
                        for j in graph:
                            run_time += j.hourly_run_time
                    day_data_list.append(run_time)
                power_source = power_source.get_power_source_display()
                dataList.append({"name": power_source, "data": day_data_list})
            dataPercentage = []
            print("calculating the percentage")
            for i in range(len(dataList)):
                x = []
                a = len(dataList[i]["data"])
                for j in range(0, a):
                    p = abs(dataList[i]["data"][j])
                    b = 0.0
                    for k in range(len(dataList)):
                        b += abs(dataList[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 1)
                    except Exception as e:
                        t = round(p, 2)
                    x.append(t)
                dataPercentage.append({"name": dataList[i]["name"], "data": x})

            print("percentage calculate")
            return Response({"Dates": dateList, "Data": dataList})
        else:
            print("###### inside different month #####")
            for power_source in SupplyLoadTimeShare.objects.distinct('power_source').order_by('power_source').filter(
                    site=site_id):
                dateList = []
                total_days = (tillDate.day - fromDate.day) + 1
                print("total days are : ", total_days)
                a = []
                for i in range(0, total_days):
                    date = fromDate.date() + timedelta(days=i)
                    print("date: ", date)
                    dateList.append(date)
                    graph = SupplyLoadTimeShare.objects.filter(site=site_id, power_source=power_source.power_source,
                                                               reading_from__date=date)
                    print("all graph object: ", graph)
                    run_time = 0.0
                    if graph.exists():
                        for j in graph:
                            run_time += j.hourly_run_time
                    a.append(run_time)
                power_source = power_source.get_power_source_display()
                dataList.append({"name": power_source, "data": a})
            dataPercentage = []
            print("calculating the percentage")
            for i in range(len(dataList)):
                x = []
                a = len(dataList[i]["data"])
                for j in range(0, a):
                    p = abs(dataList[i]["data"][j])
                    b = 0.0
                    for k in range(len(dataList)):
                        b += abs(dataList[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 2)
                    except Exception as e:
                        t = p
                    x.append(t)

                dataPercentage.append({"name": dataList[i]["name"], "data": x})
            print("percentage calculate")
            return Response({"Dates": dateList, "Data": dataList})


class PowerDistributionHourlyBarChartTime(APIView):
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        date = data.get("date", '')
        date = datetime.strptime(date, "%Y/%m/%d")
        hourList = []
        dataList = []
        for power_source in SupplyLoadTimeShare.objects.distinct('power_source').order_by('power_source').filter(
                site=site_id):
            hour_data_list = []
            hourList = []
            for i in range(24):
                hour = i
                if hour <= 9:
                    hr = "0" + str(hour) + ":00"
                else:
                    hr = str(hour) + ":00"
                print("hour : ", hr)
                hourList.append(hr)
                graph = SupplyLoadTimeShare.objects.filter(site=site_id, power_source=power_source.power_source,
                                                           reading_from__date=date,
                                                           reading_from__hour=hour)
                print("all graph object :", graph)
                run_time = 0.0
                if graph.exists():
                    for j in graph:
                        run_time += j.hourly_run_time
                hour_data_list.append(run_time)
            power_source = power_source.get_power_source_display()
            dataList.append({"name": power_source, "data": hour_data_list})

        dataPercentage = []
        print("calculating the percentage")
        for i in range(len(dataList)):
            x = []
            a = len(dataList[i]["data"])
            for j in range(0, a):
                p = abs(dataList[i]["data"][j])
                b = 0.0
                for k in range(len(dataList)):
                    b += abs(dataList[k]["data"][j])
                try:
                    t = round(p * 100 / b, 2)
                except Exception as e:
                    t = p
                x.append(t)
            dataPercentage.append({"name": dataList[i]["name"], "data": x})
        print("percentage calculate")
        return Response({"Hours": hourList, "Data": dataPercentage})


class PowerSourceDistributionMonthlyBarChart(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        till_date = data.get("till_date", "")
        print("till_date", till_date)
        from_date = data.get("from_date", "")
        print("from date: ", from_date)
        site_id = data.get("site_id", " ")
        print("This is the site id: ", site_id)
        site = Site.objects.get(id=int(site_id))
        print("site: ", site)
        try:
            from_date = datetime.strptime(from_date, '%Y/%m/%d')
            till_date = datetime.strptime(till_date, '%Y/%m/%d')
            data = []
            dates = []
            print("distinct legs")
            for leg in DailySiteReading.objects.distinct('leg_id').filter(associated_Site=int(site_id)):
                daily_consumption = []
                dates = []
                print("limits")
                dateLowerLimitCheck = from_date.date()
                dateUpperLimitCheck = till_date.date()
                print("dateUpperLimitCheck", dateUpperLimitCheck)
                given_date_graph_data = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg,
                                                                        reading_for__gte=dateLowerLimitCheck,
                                                                        reading_for__lte=dateUpperLimitCheck)
                date = from_date.date()
                print("date", date)
                print("LOOP!!")
                for i in range(31):
                    if date <= till_date.date():
                        dates.append(date)
                        print("here is range date", date)
                        if given_date_graph_data.filter(reading_for=date).exists():
                            one_day_consumption = round(
                                given_date_graph_data.filter(reading_for=date)[0].unit_consumption, 2)
                        else:
                            one_day_consumption = 0
                        daily_consumption.append(one_day_consumption)
                    else:
                        break

                    if AisleGroup.objects.filter(attached_leg_id=leg).exists():
                        aisle_group = AisleGroup.objects.get(attached_leg_id=leg).aisleGroupName
                    else:
                        aisle_group = str(leg)
                    date = date + timedelta(days=1)
                singleData = {"name": aisle_group, "data": daily_consumption}
                data.append(singleData)
            dataPercentage = []
            print("calculating the percentage")
            for i in range(len(data)):
                x = []
                a = len(data[i]["data"])
                for j in range(0, a):
                    p = abs(data[i]["data"][j])
                    b = 0.0
                    for k in range(len(data)):
                        b += abs(data[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 1)
                    except Exception as e:
                        t = round(p, 2)
                    x.append(t)
                dataPercentage.append({"name": data[i]["name"], "data": x})
            print("percentage calculate")
            return Response({"Dates": dates, "Data": dataPercentage})
        except Exception as e:
            print('exception is ', e)
            return Response({"error": "errorrrrrrrrrrrrrrrrr"})


class PowerDistributionHourlyBarChart(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        date = data.get("date", "")
        print("input date: ", date)
        date = datetime.strptime(date, "%Y/%m/%d")
        site_id = data.get("site_id", " ")
        print("This is the site id: ", site_id)
        site = Site.objects.get(id=site_id)
        print("site: ", site)
        try:
            data = []
            hours = []
            for leg in HourlySiteReading.objects.distinct('leg_id').filter(associated_Site=site):
                print("leg id is:", leg)
                hourly_consumption = []
                hours = []
                for i in range(24):
                    hr = i
                    if hr <= 9:
                        hr = "0" + str(hr) + ":00"
                    else:
                        hr = str(hr) + ":00"
                    hours.append(hr)
                    hour = date.replace(hour=i)
                    print("hour :", hour)
                    hours_graph_data = HourlySiteReading.objects.filter(associated_Site=site, leg_id=leg,
                                                                        reading_from=hour)
                    print("hours_graph_data", hours_graph_data)
                    if hours_graph_data.exists():
                        one_hour_consumption = round(hours_graph_data[0].unit_consumption, 2)
                        print("one_hour_consumption", one_hour_consumption)
                    else:
                        one_hour_consumption = 0.0
                    hourly_consumption.append(one_hour_consumption)
                    if AisleGroup.objects.filter(attached_leg_id=leg).exists():
                        aisle_group = AisleGroup.objects.get(attached_leg_id=leg).aisleGroupName
                    else:
                        aisle_group = str(leg)
                singleData = {"name": aisle_group, "data": hourly_consumption}
                print("singleData:", singleData)
                data.append(singleData)
            dataPercentage = []
            print("calculating the percentage")
            for i in range(len(data)):
                x = []
                a = len(data[i]["data"])
                print("here is a value :", a)
                for j in range(0, a):
                    p = abs(data[i]["data"][j])
                    b = 0.0
                    for k in range(len(data)):
                        b += abs(data[k]["data"][j])
                    try:
                        t = round(p * 100 / b, 2)
                    except Exception as e:
                        t = p
                    x.append(t)

                dataPercentage.append({"name": data[i]["name"], "data": x})
            print("percentage calculate")
            return Response({"Hours": hours, "Data": dataPercentage})

        except Exception as e:
            print('exception is ', e)
            return Response({"error": "errorrrrrrrrrrrrrrrrr"})


class CustomerSnapshotApiOld(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data%%%%%%%%%%% :", data)
        customer_id = data.get("id", '')
        user_type = data.get("user_type")
        all_site = Site.objects.filter(customer=customer_id, site_type=2)
        live_date = all_site[0].live_date.date()
        print("live_date :", live_date)
        baseline_date = all_site[0].baseline_date.date()
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        energyConsumed = 0.0
        energySaved = 0.0
        alarm = 0
        for i in all_site:
            alarm += AlarmNotifications.objects.filter(site_id=i.id, user_level=4).count()
            if user_type == 1:
                aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=i.id, reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date,
                                                        leg_id__in=all_leg_id)
            else:
                if int(customer_id) == 27:  # for fan separate site
                    print("for fan site")
                    aisle_group = AisleGroup.objects.filter(
                        Q(site_id=i.id) & Q(is_visible=True) | Q(attached_leg_id__in=[259, 260, 261]))
                else:
                    print("for other customers")
                    aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=i.id, reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, reading_for__lte=previous_date,
                                                        is_visible=True)
            if daily.exists():
                for j in daily:
                    energyConsumed += j.unit_consumption
                    energySaved += j.energy_saved
            else:
                energyConsumed += 0.0
                energySaved += 0.0
        try:
            percentageSaved = str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
        except Exception as e:
            print("exception is", e)
            percentageSaved = str(0.0) + " %"
        return Response({"result": 1, "alarms": alarm,
                         "energy_consumed": round(energyConsumed, 1),
                         "saved_energy": round(energySaved, 1),
                         "percentage_saved": percentageSaved
                         })


'''class CustomerSnapshotApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data%%%%%%%%%%% :", data)
        customer_id = data.get("id", '')
        user_type = data.get("user_type")
        all_site = Site.objects.filter(customer=customer_id, site_type=2)
        live_date = all_site[0].live_date.date()
        print("live_date :", live_date)
        baseline_date = all_site[0].baseline_date.date()
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        carbon_visible = False
        carbon_emission_value = 0
        if all_site[0].is_carbon_emission_visible:
            carbon_emission_value = all_site[0].carbon_emission_value
            carbon_visible = True
        energyConsumed = 0.0
        energySaved = 0.0
        carbon_saved = 0.0
        alarm = 0
        for i in all_site:
            alarm += AlarmNotifications.objects.filter(site_id=i.id, user_level=4).count()
            if user_type == 1:
                aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=i.id, reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date,
                                                        leg_id__in=all_leg_id)
            else:
                if int(customer_id) == 27:  # for fan separate site
                    print("for fan site")
                    aisle_group = AisleGroup.objects.filter(
                        Q(site_id=i.id) & Q(is_visible=True) | Q(attached_leg_id__in=[259, 260, 261]))
                else:
                    print("for other customers")
                    aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=i.id, reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, reading_for__lte=previous_date,
                                                        is_visible=True)
            if daily.exists():
                for j in daily:
                    energyConsumed += j.unit_consumption
                    energySaved += j.energy_saved
            else:
                energyConsumed += 0.0
                energySaved += 0.0
        if carbon_visible:
            carbon_saved = energySaved * carbon_emission_value
            print("carbon_saved", carbon_saved)
        try:
            percentageSaved = str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
        except Exception as e:
            print("exception is", e)
            percentageSaved = str(0.0) + " %"
        if energySaved < 0:
            energySaved = 0.0
            percentageSaved = str(0.0) + " %"
        if carbon_saved > 0:
            return Response({"result": 1, "alarms": alarm,
                             "energy_consumed": round(energyConsumed, 1),
                             "saved_energy": round(energySaved, 1),
                             "percentage_saved": percentageSaved,
                             "carbon_saved": round(carbon_saved, 1)
                             })
        else:
            return Response({"result": 1, "alarms": alarm, "energy_consumed": round(energyConsumed, 1),
                             "saved_energy": round(energySaved, 1),
                             "percentage_saved": percentageSaved})
'''


class CustomerSnapshotApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data%%%%%%%%%%% :", data)
        customer_id = data.get("id", '')
        user_type = data.get("user_type")
        if user_type == 5:
            all_site = CustomerSiteManager.objects.get(customer=customer_id)
            all_site = all_site.associated_site.filter(site_type=2)
        else:
            all_site = Site.objects.filter(customer=customer_id, site_type=2)
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        carbon_visible = False
        carbon_emission_value = 0
        energyConsumed = 0.0
        energySaved = 0.0
        carbon_saved = 0.0
        alarm = 0
        Baseline = 0.0
        for i in all_site:
            live_date = i.live_date.date()
            print("live_date :", live_date)
            try:
                baseline_date = i.baseline_date.date()
                if i.is_carbon_emission_visible:
                    carbon_emission_value = i.carbon_emission_value
                    carbon_visible = True
            except Exception as err:
                baseline_date = live_date
            alarm += AlarmNotifications.objects.filter(site_id=i.id, user_level=4).count()
            if user_type == 1:
                aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=i.id, reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date,
                                                        leg_id__in=all_leg_id)
            else:
                if int(customer_id) == 27:  # for fan separate site
                    print("for fan site")
                    aisle_group = AisleGroup.objects.filter(
                        Q(site_id=i.id) & Q(is_visible=True) | Q(attached_leg_id__in=[259, 260, 261]))
                else:
                    print("for other customers")
                    aisle_group = AisleGroup.objects.filter(site_id=i.id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=i.id, reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, reading_for__lte=previous_date,
                                                        is_visible=True)
            if daily.exists():
                for j in daily:
                    energyConsumed += j.unit_consumption
                    Baseline += j.daily_baseline_value

            else:
                energyConsumed += 0.0
                energySaved += 0.0
            energySaved = Baseline - energyConsumed
            if carbon_visible:
                carbon_saved += energySaved * carbon_emission_value
            print("carbon_saved", carbon_saved)
        try:
            percentageSaved = str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
        except Exception as e:
            print("exception is", e)
            percentageSaved = str(0.0) + " %"
        if energySaved < 0:
            energySaved = 0.0
            percentageSaved = str(0.0) + " %"
        if carbon_saved > 0:
            return Response({"result": 1, "alarms": alarm,
                             "energy_consumed": round(energyConsumed, 1),
                             "saved_energy": round(energySaved, 1),
                             "percentage_saved": percentageSaved,
                             "carbon_saved": round(carbon_saved, 1)
                             })
        else:
            return Response({"result": 1, "alarms": alarm, "energy_consumed": round(energyConsumed, 1),
                             "saved_energy": round(energySaved, 1),
                             "percentage_saved": percentageSaved})


class ParticularCustomerInfo(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data in particular customer :", data)
        user_id = data.get("id", "")
        user = User.objects.get(id=user_id).id
        customer = CustomerInfo.objects.get(customer=user)
        serializer = CustomerInfoSerializer(customer)
        return Response({"result": 1, "data": serializer.data})


class TotalAlarmsOnCustomerPageTabularForm(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        user_id = data.get("id", "")
        user = User.objects.get(id=user_id)
        all_alarms = AlarmNotifications.objects.filter(created_by=user, user_level=4).distinct("Alarm_type")
        all_sites = Site.objects.select_related('customer').filter(customer=user)
        data_list = []
        for i in all_sites:
            site_id = i.id
            site_name = i.site_name
            site_type = i.get_site_type_display()
            alarm_list = {}
            total_alarms = 0
            for j in all_alarms:
                alarm = AlarmNotifications.objects.filter(created_by=user, site_id=i, user_level=4,
                                                          Alarm_type=j.Alarm_type)
                if alarm.exists():
                    alarm_name = j.get_Alarm_type_display()
                    alarm_count = alarm.count()
                    alarm_list[alarm_name] = alarm_count
                    total_alarms += alarm_count
            if len(alarm_list) == 0:
                pass
            else:
                data_list.append({
                    "site_id": site_id,
                    "site_name": site_name,
                    "alarms": alarm_list,
                    "total_alarm_count": total_alarms,
                    "site_type": site_type
                })
        print("data list of alarms on customer page: ", data_list)
        return Response({"result": '1', "data": data_list})


class TotalAlarmsTypeCountOnCustomerPage(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        user_id = data.get("id", "")
        user = User.objects.get(id=user_id)
        all_alarms = AlarmNotifications.objects.filter(created_by=user).distinct('Alarm_type')
        data_list = []
        alarm_name_list = []
        alarm_count_list = []
        for i in all_alarms:
            print("i value: ", i)
            alarm_name = i.get_Alarm_type_display()
            print("alarm name: ", alarm_name)
            alarm_count = AlarmNotifications.objects.filter(created_by=user, Alarm_type=i.Alarm_type).count()
            print("alarm count: ", alarm_count)
            data_list.append({"name": alarm_name, "data": [alarm_count], "type": "column"})
            alarm_name_list.append(alarm_name)
            # alarm_count_list.append(alarm_count)
        return Response({"result": 1, "Data": data_list, "alarm_name_list": alarm_name_list})


'''class ParticularSiteSnapshotEnergySavingApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        # print("data of site snapshot", data)
        site_id = data.get("site_id", '')
        # print("site id is: ", site_id)
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        live_date = site.live_date.date()
        # print("live_date :",live_date)
        user_type = data.get("user_type")
        # print("site data", site)
        current_date = datetime.now()
        previous_date = current_date-timedelta(days=1)
        previous = datetime.strftime(previous_date, "%d-%b-%Y")
        if int(data.get("site_id", '')) == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023)
        else:
            baseline_date = site.baseline_date.date()
        date = datetime.strftime(baseline_date, "%d-%b-%Y")
        alarm = AlarmNotifications.objects.filter(site_id=site, user_level=4).count()
        # print("alarm count on site page: ", alarm)
        # daily = DailySiteReading.objects.filter(associated_Site=site)
        if site.live_date:
            # print("inside live date if condition: ")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                        reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date,
                                                        is_visible=True)

            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                        reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date,is_visible=True)
                live_date = site.live_date
                live_date = datetime.strftime(live_date, "%Y/%m/%d")

        else:
            # print("inside else condition. site is not live")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site, reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id,reading_for__lte=previous_date,
                                                        is_visible=True)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site,reading_for__lte=previous_date,
                                                        reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, )
                live_date = "Not Live yet"
        energyConsumed = 0.0
        energySaved = 0.0
        for i in daily:
            # print("inside for loop!!!!")
            energyConsumed += i.unit_consumption
            if i.energy_saved >= 0:
                energySaved += i.energy_saved

        try:
            percentageSaved = str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
            # live_date = site.live_date
            # live_date = datetime.strftime(live_date, "%Y/%m/%d")
        except Exception as e:
            print("exception is", e)
            percentageSaved = str(0.0) + " %"
        return Response({"result": 1, "alarms": alarm,
                         "energy_consumed": str(round(energyConsumed, 1)),
                         "saved_energy": str(round(energySaved, 1)),
                         "percentage_saved": percentageSaved,
                         "live_date": date,"previous_date":previous})'''


class ParticularSiteSnapshotEnergySavingApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        # print("data of site snapshot", data)
        site_id = data.get("site_id", '')
        # print("site id is: ", site_id)
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        carbon_visible = False
        carbon_emission_value = 0
        if site.is_carbon_emission_visible:
            carbon_emission_value = site.carbon_emission_value
            carbon_visible = True
        live_date = site.live_date
        # print("live_date :",live_date)
        user_type = data.get("user_type")
        # print("site data", site)
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        previous = datetime.strftime(previous_date, "%d-%b-%Y")
        if int(data.get("site_id", '')) == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023)
        else:
            baseline_date = site.baseline_date.date()
        date = datetime.strftime(baseline_date, "%d-%b-%Y")
        alarm = AlarmNotifications.objects.filter(site_id=site, user_level=4).count()
        # print("alarm count on site page: ", alarm)
        # daily = DailySiteReading.objects.filter(associated_Site=site)
        if site.live_date:
            # print("inside live date if condition: ")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                        reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date,
                                                        is_visible=True)

            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                        reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date, is_visible=True)
                live_date = site.live_date
                live_date = datetime.strftime(live_date, "%Y/%m/%d")

        else:
            # print("inside else condition. site is not live")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site, reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, reading_for__lte=previous_date,
                                                        is_visible=True)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(associated_Site=site, reading_for__lte=previous_date,
                                                        reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, )
                live_date = "Not Live yet"
        energyConsumed = 0.0
        energySaved = 0.0
        carbon_saved = 0.0

        for i in daily:
            # print("inside for loop!!!!")
            energyConsumed += i.unit_consumption
            # if i.energy_saved >= 0:
            energySaved += i.daily_baseline_value
        energySaved = energySaved - energyConsumed
        if carbon_visible:
            carbon_saved = energySaved * carbon_emission_value
        try:
            percentageSaved = str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
            # live_date = site.live_date
            # live_date = datetime.strftime(live_date, "%Y/%m/%d")
        except Exception as e:
            print("exception is", e)
            percentageSaved = str(0.0) + " %"
        return Response({"result": 1, "alarms": alarm,
                         "energy_consumed": str(round(energyConsumed, 1)),
                         "saved_energy": str(round(energySaved, 1)),
                         "carbon_emission_saved": str(round(carbon_saved, 1)),
                         "percentage_saved": percentageSaved,
                         "live_date": date, "previous_date": previous,"site_live_date":live_date})


class EnergySavingMonthlyBarChartOld(APIView):
    @entryExit
    def post(self, request):
        t1 = time.time()
        data = request.data
        site_id = data.get("site_id", '')
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        live_date = site.live_date
        previous_date = live_date - timedelta(days=1)
        from_date = data.get("from_date", '')
        till_date = data.get("till_date", '')
        user_type = int(data.get("user_type", ''))
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        currentDate = datetime.now()
        dateList = []
        dataList = []
        savingDataList = []
        if tillDate.month == currentDate.month:
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
            for aisle in aisle_group:
                leg = aisle.attached_leg_id
                dateList = []
                unitConsumptionList = []
                savingConsumptionList = []
                daily_data = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, is_visible=True)
                for i in range(30):
                    date = tillDate - timedelta(days=29 - i)
                    dateList.append(date.date())
                    unit_consumption = 0.0
                    energy_saved = 0.0
                    if currentDate.date() == date.date():
                        if (site.is_live and user_type in [4, 5] and live_date.date() <= date.date()) or user_type == 1:
                            hourly = HourlySiteReading.objects.filter(associated_Site=site, leg_id=leg,
                                                                      reading_from__date=date.date(), is_visible=True)
                            for k in hourly:
                                unit_consumption += k.unit_consumption
                                energy_saved += k.energy_saved
                        unitConsumptionList.append(round(unit_consumption, 2))
                        savingConsumptionList.append(round(energy_saved, 2))
                    else:
                        if user_type in [4, 5] and previous_date.date() < date.date():
                            daily = daily_data.filter(reading_for=date)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                                    energy_saved += j.energy_saved
                            unitConsumptionList.append(round(unit_consumption, 2))
                            savingConsumptionList.append(round(energy_saved, 2))
                        elif user_type == 1:
                            daily = daily_data.filter(reading_for=date)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                                    energy_saved += j.energy_saved
                            unitConsumptionList.append(round(unit_consumption, 2))
                            savingConsumptionList.append(round(energy_saved, 2))
                        else:
                            unitConsumptionList.append(0)
                            savingConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg
                dataList.append({"name": name, "data": unitConsumptionList, 'type': 'column'})
                savingDataList.append({"name": name, "data": savingConsumptionList, 'type': 'column'})
            if site.is_live:
                if int(data.get("site_id", '')) == 34:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276])
                else:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                baselineList = []
                if baseline.exists():
                    if int(data.get("site_id", '')) == 34:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                            aisle_group__in=[259, 260, 261,
                                                                                             276])
                    elif int(data.get("site_id", '')) == 29:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                            Q(aisle_group__in=[259, 260, 261, 276]))
                    else:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                    # latest_baseline_value = latest_baseline_value['baseline_value__sum']
                    for i in range(30):
                        date = tillDate - timedelta(days=29 - i)
                        baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                            Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                            Sum('baseline_value'))
                        try:
                            baseline_value = baseline_value['baseline_value__sum']
                            if baseline_value is not None:
                                baselineList.append(round(baseline_value, 2))
                            else:
                                baselineList.append(0)
                        except Exception as e:
                            print('Exception 1 is', e)
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
        else:
            total_days = (tillDate.day - fromDate.day) + 1
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
            for aisle in aisle_group:
                leg = aisle.attached_leg_id
                unitConsumptionList = []
                savingConsumptionList = []
                dateList = []
                daily_data = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, is_visible=True)
                for i in range(0, total_days):
                    date = tillDate - timedelta(days=(total_days - 1) - i)
                    dateList.append(date.date())
                    if user_type in [4, 5] and previous_date.date() < date.date():
                        daily = daily_data.filter(reading_for=date)
                        unit_consumption = 0.0
                        energy_saved = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption
                                energy_saved += j.energy_saved

                        unitConsumptionList.append(round(unit_consumption, 2))
                        savingConsumptionList.append(round(energy_saved, 2))
                    elif user_type == 1:
                        daily = daily_data.filter(reading_for=date)
                        unit_consumption = 0.0
                        energy_saved = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption
                                energy_saved += j.energy_saved

                        unitConsumptionList.append(round(unit_consumption, 2))
                        savingConsumptionList.append(round(energy_saved, 2))
                    else:
                        unitConsumptionList.append(0)
                        savingConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg.leg_id
                dataList.append({"name": name, "data": unitConsumptionList, 'type': 'column'})
                savingDataList.append({"name": name, "data": savingConsumptionList, 'type': 'column'})
            if site.is_live:
                if int(data.get("site_id", '')) == 34:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276])
                else:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                baselineList = []
                if baseline.exists():
                    if int(data.get("site_id", '')) == 34:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                            aisle_group__in=[259, 260, 261,
                                                                                             276])
                    elif int(data.get("site_id", '')) == 29:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                            Q(aisle_group__in=[259, 260, 261, 276]))
                    else:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                    for i in range(total_days):
                        date = tillDate - timedelta(days=(total_days - 1) - i)
                        baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                            Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                            Sum('baseline_value'))
                        try:
                            baseline_value = baseline_value['baseline_value__sum']
                            if baseline_value is not None:
                                baselineList.append(round(baseline_value, 2))
                            else:
                                baselineList.append(0)
                        except Exception as e:
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                            print('Exception 2 is', e)
                dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
        t2 = time.time()
        return Response({"result": 1, "Dates": dateList, "Data": dataList, "SavingData": savingDataList})



class SubmeteringMonthlyBarChart(APIView):
    @entryExit
    def post(self, request):
        t1 = time.time()
        # print("initial time : ", t1)
        data = request.data
        site_id = data.get("site_id", '')
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        print("site : ", site)
        live_date = site.live_date
        # print("live data", live_date)
        previous_date = live_date - timedelta(days=1)
        # print("previous_date :", previous_date)
        from_date = data.get("from_date", '')
        till_date = data.get("till_date", '')
        user_type = int(data.get("user_type", ''))
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        currentDate = datetime.now()
        dateList = []
        dataList = []
        if tillDate.month == currentDate.month:
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
            for aisle in aisle_group:
                # print("i : ", aisle)
                leg = aisle.attached_leg_id
                # aisle_group = AisleGroup.objects.filter(site_id=site_id, attached_leg_id=leg.leg_id)
                dateList = []
                unitConsumptionList = []
                daily_data = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, is_visible=True)
                for i in range(30):
                    date = tillDate - timedelta(days=29 - i)
                    dateList.append(date.date())
                    unit_consumption = 0.0
                    if currentDate.date() == date.date():
                        # print("current date is ", date)
                        if (site.is_live and user_type in [4, 5] and live_date.date() <= date.date()) or user_type == 1:
                            hourly = HourlySiteReading.objects.filter(associated_Site=site, leg_id=leg,
                                                                      reading_from__date=date.date(), is_visible=True)
                            for k in hourly:
                                # print("one entry of hourly", k)
                                unit_consumption += k.unit_consumption
                        unitConsumptionList.append(round(unit_consumption, 2))
                    else:
                        # print("other dates are ", date)
                        if user_type in [4, 5] and previous_date.date() < date.date():
                            # print("inside if")
                            # if (site.is_live and user_type == 4 and live_date.date() <= date.date()) or user_type == 1:
                            daily = daily_data.filter(reading_for=date)
                            # daily = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, reading_for=date, is_visible=True)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                            unitConsumptionList.append(round(unit_consumption, 2))
                        elif user_type == 1:
                            daily = daily_data.filter(reading_for=date)
                            if daily.exists():
                                for j in daily:
                                    unit_consumption += j.unit_consumption
                            unitConsumptionList.append(round(unit_consumption, 2))
                        else:
                            # print("inside else")
                            unitConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg
                dataList.append({"name": name, "data": unitConsumptionList, 'type': 'column'})

        else:
            total_days = (tillDate.day - fromDate.day) + 1
            # all_leg_id = DailySiteReading.objects.filter(associated_Site=site).distinct("leg_id")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
            for aisle in aisle_group:
                leg = aisle.attached_leg_id
                unitConsumptionList = []
                dateList = []
                daily_data = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, is_visible=True)
                for i in range(0, total_days):
                    date = tillDate - timedelta(days=(total_days - 1) - i)
                    dateList.append(date.date())
                    if user_type in [4, 5] and previous_date.date() < date.date():
                        # print("inside if")
                        daily = daily_data.filter(reading_for=date)
                        # daily = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, reading_for=date, is_visible=True)
                        unit_consumption = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption

                        unitConsumptionList.append(round(unit_consumption, 2))
                    elif user_type == 1:
                        daily = daily_data.filter(reading_for=date)
                        unit_consumption = 0.0
                        if daily.exists():
                            for j in daily:
                                unit_consumption += j.unit_consumption
                        unitConsumptionList.append(round(unit_consumption, 2))
                    else:
                        unitConsumptionList.append(0)
                if aisle:
                    name = aisle.aisleGroupName
                else:
                    name = leg.leg_id
                dataList.append({"name": name, "data": unitConsumptionList, 'type': 'column'})
        t2 = time.time()
        return Response({"result": 1, "Dates": dateList, "Data": dataList})


class DemoApi(APIView):
    @entryExit
    def get(self, request):
        data = request.data
        my_list = []
        daily = DailySiteReading.objects.filter(associated_Site=1)
        for i in daily:
            my_list.append({"consumption": i.unit_consumption, "saving": i.energy_saved, "date": i.reading_for})
        return Response({"result": 1, "data": my_list})


'''class EnergySavingMonthlyTrendApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", '')
        user_type = data.get("user_type")
        current_date = datetime.now().replace(day=15)
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        live_date = site.live_date.date()
        if int(data.get("site_id", '')) == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023)
        else:
            baseline_date = site.baseline_date.date()
        previous_date = live_date - timedelta(days=1)
        print("previous_date", previous_date)
        previous_month_year = live_date.strftime("%Y-%m")
        print("previous_month_year", previous_month_year)
        today_date = datetime.now()
        current = today_date - timedelta(days=1)
        month_list = []
        energy_consumed_list = []
        energy_saved_list = []
        percentage_saved_list = []
        if site:
            for i in range(11, -1, -1):
                energyConsumed = 0
                energySaved = 0
                month = current_date - timedelta(i * 365 / 12)
                print("month%%%%", month)
                print("month##### : ", month.date())
                date_in_str = month.strftime('%b')
                year_in_str = month.strftime("%Y")
                modified_date = date_in_str + "-" + year_in_str
                month_list.append(modified_date)
                print("converted month###", date_in_str)
                print("site live date###: ", live_date)
                print("previous date###", previous_date)
                month_year = month.strftime("%Y-%m")
                print("month_year", month_year)
                if previous_month_year <= month_year:
                    # if True:
                    print("inside if")
                    if previous_date.month == month.month:
                        print("again if")
                        print("live date month is same with this month")
                        if user_type == 1:
                            print("inside userType superadmin")
                            if int(data.get('site_id')) == 34:
                                aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                            else:
                                aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                            # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                            all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                            print("All legs", all_leg_id)
                            daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                                    reading_for__year=month.year,
                                                                    reading_for__gte=baseline_date,
                                                                    reading_for__lte=current,
                                                                    reading_for__month=month.month,
                                                                    is_visible=True)
                            print("daily data :", daily)
                        else:
                            print("inside userType customers")
                            if int(data.get('site_id')) == 34:
                                aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                            else:
                                aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                            all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                            print("All legs", all_leg_id)
                            daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                                    reading_for__year=month.year,
                                                                    reading_for__gte=baseline_date,
                                                                    reading_for__lte=current,
                                                                    reading_for__month=month.month, is_visible=True)
                            print("daily :", daily)
                        if daily.exists():
                            for j in daily:
                                energyConsumed += j.unit_consumption
                                # print("energyConsumed",energyConsumed)
                                if j.energy_saved >= 0:
                                    energySaved += j.energy_saved
                    else:
                        print("live date month is not same with this month")
                        if user_type == 1:
                            if int(data.get('site_id')) == 34:
                                aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                            else:
                                aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                            # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                            all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                            daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                                    reading_for__year=month.year,
                                                                    reading_for__gte=baseline_date,
                                                                    reading_for__lte=current,
                                                                    reading_for__month=month.month,
                                                                    is_visible=True)
                        else:
                            if int(data.get('site_id')) == 34:
                                aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261,276])
                            else:
                                aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                            all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                            daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                                    reading_for__year=month.year,
                                                                    reading_for__month=month.month,
                                                                    reading_for__gte=baseline_date,
                                                                    reading_for__lte=current,
                                                                    is_visible=True)
                            print(date_in_str + " month data :", daily)
                        if daily.exists():
                            for j in daily:
                                energyConsumed += j.unit_consumption
                                if j.energy_saved >= 0:
                                    energySaved += j.energy_saved
                else:
                    print("inside else")
                    energyConsumed = 0
                    energySaved = 0
                try:
                    percentage_saved = round(energySaved * 100 / (energySaved + energyConsumed), 1)
                    percentage_saved_list.append(percentage_saved)
                except Exception as e:
                    print("exception EnergySavingMonthlyTrendApi is:", e)
                    percentage_saved = 0.0
                    percentage_saved_list.append(percentage_saved)
                energy_consumed_list.append(round(energyConsumed, 1))
                energy_saved_list.append(round(energySaved, 1))
        return Response({"result": 1, "months": month_list, "energySaved": energy_saved_list,
                         "energyConsumed": energy_consumed_list,
                         "percentageSaved": percentage_saved_list})'''


# class EnergySavingMonthlyTrendApi(APIView):
#     permission_classes = [AllowAny]
#     @entryExit
#     def post(self, request):
#         from django.core.cache import cache
#         import hashlib
        
#         data = request.data
#         site_id = data.get("site_id", '')
#         user_type = data.get("user_type")
        
#         # Safe integer conversion for site_id
#         try:
#             site_id_int = int(site_id)
#         except (ValueError, TypeError):
#             # If site_id is missing or empty, handle gracefully (though logic below expects valid site)
#              return Response({"error": "Invalid or missing site_id"}, status=status.HTTP_400_BAD_REQUEST)

#         # Get current month/year for comparison
#         today_date = datetime.now()
#         current_month = today_date.month
#         current_year = today_date.year
        
#         # If not in cache, proceed with normal processing
#         current_date = datetime.now().replace(day=15)
        
#         # Handle virtual site 34 -> 29 logic locally for query but keep original for other logic references if needed
#         query_site_id = site_id_int
#         if site_id_int == 34:
#             query_site_id = 29
            
#         try:
#             site = Site.objects.get(id=query_site_id)
#         except Site.DoesNotExist:
#              return Response({"error": "Site not found"}, status=status.HTTP_404_NOT_FOUND)

#         carbon_visible = False
#         carbon_emission_value = 0
#         if site.is_carbon_emission_visible:
#             carbon_emission_value = site.carbon_emission_value
#             carbon_visible = True
            
#         live_date = site.live_date.date()
        
#         if site_id_int == 34:
#             baseline_date = datetime.now().replace(day=12, month=4, year=2023)
#         else:
#             baseline_date = site.baseline_date.date()
            
#         previous_date = live_date - timedelta(days=1)
#         previous_month_year = live_date.strftime("%Y-%m")
#         current = today_date - timedelta(days=1)
        
#         month_list = []
#         energy_consumed_list = []
#         carbon_list = []
#         energy_saved_list = []
#         percentage_saved_list = []
        
#         if site:
#             for i in range(11, -1, -1):
#                 month = current_date - timedelta(i * 365 / 12)
#                 month_str = month.strftime('%Y-%m')
                
#                 # Check if this is the current month
#                 is_current_month = (month.month == current_month and month.year == current_year)
                
#                 # Create cache key for this specific month
#                 cache_key_data = f"energy_monthly_trend:site_{site_id}:user_{user_type}:month_{month_str}"
#                 cache_key = hashlib.md5(cache_key_data.encode()).hexdigest()
                
#                 # Try to get cached data for previous months only
#                 if not is_current_month:
#                     cached_month_data = cache.get(cache_key)
#                     if cached_month_data:
#                         # Use cached data for this month
#                         month_list.append(cached_month_data['month'])
#                         energy_consumed_list.append(cached_month_data['energy_consumed'])
#                         energy_saved_list.append(cached_month_data['energy_saved'])
#                         carbon_list.append(cached_month_data['carbon_saved'])
#                         percentage_saved_list.append(cached_month_data['percentage_saved'])
#                         continue
                
#                 # Calculate data for this month (either current month or cache miss)
#                 energyConsumed = 0
#                 energySaved = 0
#                 carbon_saved = 0
#                 date_in_str = month.strftime('%b')
#                 year_in_str = month.strftime("%Y")
#                 modified_date = date_in_str + "-" + year_in_str
#                 month_list.append(modified_date)
#                 month_year = month.strftime("%Y-%m")
                
#                 if previous_month_year <= month_year:
#                     if previous_date.month == month.month:
#                         if user_type == 1:
#                             if site_id_int == 34:
#                                 aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
#                             else:
#                                 aisle_group = AisleGroup.objects.filter(virtual_siteID=query_site_id, is_visible=True)
#                             all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
#                             daily = DailySiteReading.objects.filter(leg_id__in=all_leg_id,
#                                                                     reading_for__year=month.year,
#                                                                     reading_for__gte=baseline_date,
#                                                                     reading_for__lte=current,
#                                                                     reading_for__month=month.month,
#                                                                     is_visible=True)
#                         else:
#                             if site_id_int == 34:
#                                 aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
#                             else:
#                                 aisle_group = AisleGroup.objects.filter(virtual_siteID=query_site_id, is_visible=True)
#                             all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
#                             daily = DailySiteReading.objects.filter(leg_id__in=all_leg_id,
#                                                                     reading_for__year=month.year,
#                                                                     reading_for__gte=baseline_date,
#                                                                     reading_for__lte=current,
#                                                                     reading_for__month=month.month, is_visible=True)
#                         if daily.exists():
#                             for j in daily:
#                                 energyConsumed += j.unit_consumption
#                                 energySaved += j.daily_baseline_value
#                                 if carbon_visible:
#                                     carbon_saved = energySaved * carbon_emission_value

#                     else:
#                         if user_type == 1:
#                             if site_id_int == 34:
#                                 aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
#                             else:
#                                 aisle_group = AisleGroup.objects.filter(virtual_siteID = query_site_id, is_visible=True)
#                             all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
#                             daily = DailySiteReading.objects.filter(leg_id__in=all_leg_id,
#                                                                     reading_for__year=month.year,
#                                                                     reading_for__gte=baseline_date,
#                                                                     reading_for__lte=current,
#                                                                     reading_for__month=month.month,
#                                                                     is_visible=True)
#                         else:
#                             if site_id_int == 34:
#                                 aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
#                             else:
#                                 aisle_group = AisleGroup.objects.filter(virtual_siteID=query_site_id, is_visible=True)
#                             all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
#                             daily = DailySiteReading.objects.filter(leg_id__in=all_leg_id,
#                                                                     reading_for__year=month.year,
#                                                                     reading_for__month=month.month,
#                                                                     reading_for__gte=baseline_date,
#                                                                     reading_for__lte=current,
#                                                                     is_visible=True)
#                         if daily.exists():
#                             for j in daily:
#                                 energyConsumed += j.unit_consumption
#                                 energySaved += j.daily_baseline_value
#                                 if carbon_visible:
#                                     carbon_saved = energySaved * carbon_emission_value
#                 else:
#                     energyConsumed = 0
#                     energySaved = 0
#                     carbon_saved = 0
                
#                 energySaved = energySaved - energyConsumed
#                 try:
#                     percentage_saved = round(energySaved * 100 / (energySaved + energyConsumed), 1)
#                     percentage_saved_list.append(percentage_saved)
#                 except Exception as e:
#                     percentage_saved = 0.0
#                     percentage_saved_list.append(percentage_saved)
                    
#                 energy_consumed_list.append(round(energyConsumed, 1))
#                 energy_saved_list.append(round(energySaved, 1))
#                 carbon_list.append(round(carbon_saved, 1))
                
#                 # Cache this month's data ONLY if it's not the current month
#                 if not is_current_month:
#                     month_cache_data = {
#                         'month': modified_date,
#                         'energy_consumed': round(energyConsumed, 1),
#                         'energy_saved': round(energySaved, 1),
#                         'carbon_saved': round(carbon_saved, 1),
#                         'percentage_saved': percentage_saved
#                     }
#                     # Cache previous months for 90 days (never changes)
#                     cache.set(cache_key, month_cache_data, timeout=60*60*24*90)
        
#         # Prepare response data
#         response_data = {
#             "result": 1, 
#             "months": month_list, 
#             "energySaved": energy_saved_list,
#             "energyConsumed": energy_consumed_list, 
#             "carbon_saved": carbon_list,
#             "percentageSaved": percentage_saved_list
#         }
        
#         return Response(response_data)


class EnergySavingMonthlyTrendApi(APIView):
    permission_classes = [AllowAny]
    @entryExit
    def post(self, request):
        from django.core.cache import cache
        import hashlib

        data = request.data
        site_id = data.get("site_id", '')
        user_type = data.get("user_type")

        try:
            site_id_int = int(site_id)
        except (ValueError, TypeError):
            return Response({"error": "Invalid or missing site_id"}, status=status.HTTP_400_BAD_REQUEST)

        today_date = datetime.now()
        current_month = today_date.month
        current_year = today_date.year
        current_date = datetime.now().replace(day=15)

        query_site_id = site_id_int
        if site_id_int == 34:
            query_site_id = 29

        try:
            site = Site.objects.get(id=query_site_id)
        except Site.DoesNotExist:
            return Response({"error": "Site not found"}, status=status.HTTP_404_NOT_FOUND)

        carbon_visible = False
        carbon_emission_value = 0
        if site.is_carbon_emission_visible:
            carbon_emission_value = site.carbon_emission_value
            carbon_visible = True

        live_date = site.live_date.date()

        if site_id_int == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023).date()
        else:
            baseline_date = site.baseline_date.date()

        baseline_date_str = baseline_date.strftime("%Y-%m-%d")
        current = (today_date - timedelta(days=1)).date()
        live_month_key = live_date.strftime("%Y-%m")

        if site_id_int == 34:
            aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
        else:
            aisle_group = AisleGroup.objects.filter(virtual_siteID=query_site_id, is_visible=True)
        all_leg_id = list(aisle_group.values_list('attached_leg_id', flat=True))

        month_list = []
        energy_consumed_list = []
        carbon_list = []
        energy_saved_list = []
        percentage_saved_list = []

        def month_bounds(reference_date):
            month_start = reference_date.replace(day=1).date()
            if reference_date.month == 12:
                next_month_start = reference_date.replace(year=reference_date.year + 1, month=1, day=1).date()
            else:
                next_month_start = reference_date.replace(month=reference_date.month + 1, day=1).date()
            return month_start, next_month_start

        for i in range(11, -1, -1):
            month = current_date - timedelta(i * 365 / 12)
            month_str = month.strftime('%Y-%m')
            modified_date = month.strftime("%b-%Y")
            month_list.append(modified_date)

            is_current_month = (month.month == current_month and month.year == current_year)
            cache_key_data = (
                f"energy_monthly_trend:site_{site_id}:user_{user_type}:"
                f"month_{month_str}:baseline_{baseline_date_str}"
            )
            cache_key = hashlib.md5(cache_key_data.encode()).hexdigest()

            if not is_current_month:
                cached_month_data = cache.get(cache_key)
                if cached_month_data:
                    energy_consumed_list.append(cached_month_data['energy_consumed'])
                    energy_saved_list.append(cached_month_data['energy_saved'])
                    carbon_list.append(cached_month_data['carbon_saved'])
                    percentage_saved_list.append(cached_month_data['percentage_saved'])
                    continue

            energy_consumed = 0.0
            energy_saved = 0.0
            carbon_saved = 0.0
            percentage_saved = 0.0

            if month_str >= live_month_key and all_leg_id:
                month_start, next_month_start = month_bounds(month)
                effective_start = max(month_start, baseline_date, live_date)
                effective_end = min(next_month_start - timedelta(days=1), current)

                if effective_start <= effective_end:
                    monthly_totals = DailySiteReading.objects.filter(
                        leg_id__in=all_leg_id,
                        reading_for__gte=effective_start,
                        reading_for__lte=effective_end,
                        is_visible=True
                    ).aggregate(
                        total_consumed=Sum('unit_consumption'),
                        total_saved=Sum('energy_saved')
                    )

                    energy_consumed = monthly_totals['total_consumed'] or 0.0
                    energy_saved = monthly_totals['total_saved'] or 0.0

                    if energy_saved < 0:
                        energy_saved = 0.0

                    if carbon_visible and energy_saved > 0:
                        carbon_saved = energy_saved * carbon_emission_value

                    if energy_consumed + energy_saved > 0:
                        percentage_saved = round(
                            energy_saved * 100 / (energy_saved + energy_consumed), 1
                        )

            energy_consumed = round(energy_consumed, 1)
            energy_saved = round(energy_saved, 1)
            carbon_saved = round(carbon_saved, 1)

            energy_consumed_list.append(energy_consumed)
            energy_saved_list.append(energy_saved)
            carbon_list.append(carbon_saved)
            percentage_saved_list.append(percentage_saved)

            if not is_current_month:
                cache.set(cache_key, {
                    'energy_consumed': energy_consumed,
                    'energy_saved': energy_saved,
                    'carbon_saved': carbon_saved,
                    'percentage_saved': percentage_saved,
                }, timeout=60 * 60 * 24 * 90)

        response_data = {
            "result": 1,
            "months": month_list,
            "energySaved": energy_saved_list,
            "energyConsumed": energy_consumed_list,
            "carbon_saved": carbon_list,
            "percentageSaved": percentage_saved_list
        }

        return Response(response_data)

'''class NewEnergySavingMonthlyTrendApi(APIView):
    @entryExit
    def post(self, request):
        try:
            from django.core.cache import cache
            data = request.data
            site_id = data.get("site_id", '')
            user_type = data.get("user_type")

            cache_key = f"energy_monthly_trend:{site_id}:{user_type}"
            cached_prev_data = cache.get(cache_key) or {}

            current_month_key = datetime.now().strftime("%Y-%m")

            current_date = datetime.now().replace(day=15)

            if int(site_id) == 34:
                site_id = 29

            site = Site.objects.get(id=site_id)

            carbon_visible = False
            carbon_emission_value = 0
            if site.is_carbon_emission_visible:
                carbon_emission_value = site.carbon_emission_value
                carbon_visible = True

            live_date = site.live_date.date()

            if int(data.get("site_id", '')) == 34:
                baseline_date = datetime.now().replace(day=12, month=4, year=2023)
            else:
                baseline_date = site.baseline_date.date()

            previous_date = live_date - timedelta(days=1)
            previous_month_year = live_date.strftime("%Y-%m")

            today_date = datetime.now()
            current = today_date - timedelta(days=1)

            month_list = []
            energy_consumed_list = []
            carbon_list = []
            energy_saved_list = []
            percentage_saved_list = []

            if site:
                for i in range(11, -1, -1):
                    month = current_date - timedelta(i * 365 / 12)
                    month_year = month.strftime("%Y-%m")

                    # 🔴 USE REDIS FOR PREVIOUS MONTHS
                    if month_year != current_month_key and cached_prev_data:
                        idx = cached_prev_data["months"].index(
                            month.strftime('%b') + "-" + month.strftime('%Y')
                        )

                        month_list.append(cached_prev_data["months"][idx])
                        energy_consumed_list.append(cached_prev_data["energyConsumed"][idx])
                        energy_saved_list.append(cached_prev_data["energySaved"][idx])
                        carbon_list.append(cached_prev_data["carbon_saved"][idx])
                        percentage_saved_list.append(cached_prev_data["percentageSaved"][idx])
                        continue

                    # 🔴 CURRENT MONTH OR CACHE MISS → ORIGINAL LOGIC
                    energyConsumed = 0
                    energySaved = 0
                    carbon_saved = 0

                    date_in_str = month.strftime('%b')
                    year_in_str = month.strftime("%Y")
                    modified_date = date_in_str + "-" + year_in_str
                    month_list.append(modified_date)

                    if previous_month_year <= month_year:

                        if previous_date.month == month.month:

                            if user_type == 1:
                                if int(data.get('site_id')) == 34:
                                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259,260,261,276,710])
                                else:
                                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                            else:
                                if int(data.get('site_id')) == 34:
                                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259,260,261,276,710])
                                else:
                                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)

                            all_leg_id = [a.attached_leg_id for a in aisle_group]

                            daily = DailySiteReading.objects.filter(
                                associated_Site=site,
                                leg_id__in=all_leg_id,
                                reading_for__year=month.year,
                                reading_for__month=month.month,
                                reading_for__gte=baseline_date,
                                reading_for__lte=current,
                                is_visible=True
                            )

                            if daily.exists():
                                for j in daily:
                                    energyConsumed += j.unit_consumption
                                    energySaved += j.daily_baseline_value
                                    if carbon_visible:
                                        carbon_saved = energySaved * carbon_emission_value

                    energySaved = energySaved - energyConsumed

                    try:
                        percentage_saved = round(
                            energySaved * 100 / (energySaved + energyConsumed), 1
                        )
                    except:
                        percentage_saved = 0.0

                    energy_consumed_list.append(round(energyConsumed, 1))
                    energy_saved_list.append(round(energySaved, 1))
                    carbon_list.append(round(carbon_saved, 1))
                    percentage_saved_list.append(percentage_saved)

            # 🔴 CACHE ONLY PREVIOUS 11 MONTHS
            cache_data = {
                "months": month_list[:-1],
                "energyConsumed": energy_consumed_list[:-1],
                "energySaved": energy_saved_list[:-1],
                "carbon_saved": carbon_list[:-1],
                "percentageSaved": percentage_saved_list[:-1]
            }

            cache.set(cache_key, cache_data, timeout=60 * 60 * 24 * 90)

            return Response({
                "result": 1,
                "months": month_list,
                "energySaved": energy_saved_list,
                "energyConsumed": energy_consumed_list,
                "carbon_saved": carbon_list,
                "percentageSaved": percentage_saved_list
            })
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})'''

class EnergySavingMonthlyTrendExcelDownload(APIView):
    def post(self, request):
        data = request.data
        try:    
            site_id = data.get("site_id", '')
            from_month = data.get("from_month", '')  # Format: 'YYYY-MM'
            to_month = data.get("to_month", '')      # Format: 'YYYY-MM'
            user_type = data.get("user_type")
            
            if not site_id or not from_month or not to_month:
                return Response({"status": 500, "data": [], "msg": "Missing required parameters: site_id, from_month, to_month"})
            
            if int(site_id) == 34:
                site_id = 29
            
            # Get site details
            site = Site.objects.get(id=site_id)
            site_name = site.site_name.replace(' ', '_').replace('/', '_')
            
            carbon_visible = False
            carbon_emission_value = 0
            if site.is_carbon_emission_visible:
                carbon_emission_value = site.carbon_emission_value
                carbon_visible = True
            
            # Match EnergySavingMonthlyTrendApi baseline date logic exactly
            if int(data.get("site_id", '')) == 34:
                baseline_date = datetime.now().replace(day=12, month=4, year=2023).date()
            else:
                baseline_date = site.baseline_date.date() if site.baseline_date else datetime.now().date()
            
            from_parts = from_month.split('-')
            to_parts = to_month.split('-')
            
            if len(from_parts) == 2:
                if len(from_parts[0]) == 4:
                    from_year, from_month_num = int(from_parts[0]), int(from_parts[1])
                else:
                    from_month_num, from_year = int(from_parts[0]), int(from_parts[1])
            else:
                return Response({"status": 500, "data": [], "msg": "Invalid month format. Use YYYY-MM"})
            
            if len(to_parts) == 2:
                if len(to_parts[0]) == 4:
                    to_year, to_month_num = int(to_parts[0]), int(to_parts[1])
                else:
                    to_month_num, to_year = int(to_parts[0]), int(to_parts[1])
            else:
                return Response({"status": 500, "data": [], "msg": "Invalid month format. Use YYYY-MM"})
            
            month_list = []
            energy_consumed_list = []
            carbon_list = []
            energy_saved_list = []
            percentage_saved_list = []
            days_in_month_list = []
            baseline_value_list = []
            
            # Generate list of months between from_month and to_month
            current_date = datetime.now()
            current = current_date - timedelta(days=1)
            start_date = datetime(from_year, from_month_num, 15)
            end_date = datetime(to_year, to_month_num, 15)
            
            current_month = start_date
            
            while current_month <= end_date:
                energyConsumed = 0
                energySaved = 0
                carbon_saved = 0
                
                date_in_str = current_month.strftime('%b')
                year_in_str = current_month.strftime("%Y")
                modified_date = date_in_str + "-" + year_in_str
                month_list.append(modified_date)
                
                # Calculate days in current month for display
                import calendar
                days_in_month = calendar.monthrange(current_month.year, current_month.month)[1]
                days_in_month_list.append(days_in_month)
                
                # Match EnergySavingMonthlyTrendApi aisle group logic exactly
                if user_type == 1:
                    if int(data.get('site_id', '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                    else:
                        aisle_group = AisleGroup.objects.filter(virtual_siteID=site_id, is_visible=True)
                else:
                    if int(data.get('site_id', '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                    else:
                        aisle_group = AisleGroup.objects.filter(virtual_siteID=site_id, is_visible=True)
                
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                
                # Match EnergySavingMonthlyTrendApi daily readings filter exactly
                daily = DailySiteReading.objects.filter(
                    associated_Site=site,
                    leg_id__in=all_leg_id,
                    reading_for__year=current_month.year,
                    reading_for__month=current_month.month,
                    reading_for__gte=baseline_date,
                    reading_for__lte=current.date(),
                    is_visible=True
                )
                
                # Match EnergySavingMonthlyTrendApi calculation logic exactly
                if daily.exists():
                    for j in daily:
                        energyConsumed += j.unit_consumption
                        energySaved += j.daily_baseline_value
                
                # Match EnergySavingMonthlyTrendApi energy saved calculation exactly
                energySaved = energySaved - energyConsumed
                
                # Calculate carbon saved only if carbon emission is visible for this site
                if carbon_visible:
                    carbon_saved = energySaved * carbon_emission_value
                
                # Match EnergySavingMonthlyTrendApi percentage calculation exactly
                try:
                    percentage_saved = round(energySaved * 100 / (energySaved + energyConsumed), 1)
                    percentage_saved_list.append(percentage_saved)
                except Exception as e:
                    print("Exception calculating percentage:", e)
                    percentage_saved_list.append(0.0)
                
                energy_consumed_list.append(round(energyConsumed, 1))
                energy_saved_list.append(round(energySaved, 1))
                carbon_list.append(round(carbon_saved, 1))
                baseline_value_list.append(round(energySaved + energyConsumed, 1))  # Total baseline = energySaved + energyConsumed
                
                # Move to next month
                if current_month.month == 12:
                    current_month = current_month.replace(year=current_month.year + 1, month=1)
                else:
                    current_month = current_month.replace(month=current_month.month + 1)
            
            # Create DataFrame - available for all user types
            if carbon_visible:
                df = pd.DataFrame({
                    "Month": month_list,
                    "Days in Month": days_in_month_list,
                    "Baseline Value (kWh)": baseline_value_list,
                    "Energy Consumed (kWh)": energy_consumed_list,
                    "Energy Saved (kWh)": energy_saved_list,
                    "Percentage Saved (%)": percentage_saved_list,
                    "Carbon Saved (kg CO2)": carbon_list
                })
            else:
                df = pd.DataFrame({
                    "Month": month_list,
                    "Days in Month": days_in_month_list,
                    "Baseline Value (kWh)": baseline_value_list,
                    "Energy Consumed (kWh)": energy_consumed_list,
                    "Energy Saved (kWh)": energy_saved_list,
                    "Percentage Saved (%)": percentage_saved_list
                })
            
            # Generate filename
            file_name = f"{site_name}_saving_monthly_trend_{from_month}_to_{to_month}.csv"
            response = HttpResponse(content_type='text/csv')
            response['filename'] = file_name
            response['Content-Disposition'] = f'attachment; filename={file_name}'
            df.to_csv(response, index=False)
            
            return response
            
        except Site.DoesNotExist:
            return Response({"status": 500, "data": [], "msg": "Site not found"})
        except Exception as err:
            print("Exception EnergySavingMonthlyTrendExcelDownload:", err)
            return Response({"status": 500, "data": [], "msg": str(err)})

class NewEnergySavingMonthlyTrendApi(APIView):
    @entryExit
    def post(self, request):
        try:
            from django.core.cache import cache
            data = request.data
            site_id = data.get("site_id", '')
            user_type = data.get("user_type")

            cache_key = f"energy_monthly_trend:{site_id}:{user_type}"
            cached_prev_data = cache.get(cache_key) or {}

            current_month_key = datetime.now().strftime("%Y-%m")

            current_date = datetime.now().replace(day=15)

            if int(site_id) == 34:
                site_id = 29

            site = Site.objects.get(id=site_id)

            carbon_visible = False
            carbon_emission_value = 0
            if site.is_carbon_emission_visible:
                carbon_emission_value = site.carbon_emission_value
                carbon_visible = True

            live_date = site.live_date.date()

            if int(data.get("site_id", '')) == 34:
                baseline_date = datetime.now().replace(day=12, month=4, year=2023)
            else:
                baseline_date = site.baseline_date.date()

            previous_date = live_date - timedelta(days=1)
            previous_month_year = live_date.strftime("%Y-%m")

            today_date = datetime.now()
            current = today_date - timedelta(days=1)

            month_list = []
            energy_consumed_list = []
            carbon_list = []
            energy_saved_list = []
            percentage_saved_list = []

            if site:
                for i in range(11, -1, -1):
                    month = current_date - timedelta(i * 365 / 12)
                    month_year = month.strftime("%Y-%m")

                    # 🔴 USE REDIS FOR PREVIOUS MONTHS
                    if month_year != current_month_key and cached_prev_data:
                        idx = cached_prev_data["months"].index(
                            month.strftime('%b') + "-" + month.strftime('%Y')
                        )

                        month_list.append(cached_prev_data["months"][idx])
                        energy_consumed_list.append(cached_prev_data["energyConsumed"][idx])
                        energy_saved_list.append(cached_prev_data["energySaved"][idx])
                        carbon_list.append(cached_prev_data["carbon_saved"][idx])
                        percentage_saved_list.append(cached_prev_data["percentageSaved"][idx])
                        continue

                    # 🔴 CURRENT MONTH OR CACHE MISS → ORIGINAL LOGIC
                    energyConsumed = 0
                    energySaved = 0
                    carbon_saved = 0

                    date_in_str = month.strftime('%b')
                    year_in_str = month.strftime("%Y")
                    modified_date = date_in_str + "-" + year_in_str
                    month_list.append(modified_date)

                    if previous_month_year <= month_year:

                        if previous_date.month == month.month:

                            if user_type == 1:
                                if int(data.get('site_id')) == 34:
                                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259,260,261,276,710])
                                else:
                                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                            else:
                                if int(data.get('site_id')) == 34:
                                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259,260,261,276,710])
                                else:
                                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)

                            all_leg_id = [a.attached_leg_id for a in aisle_group]

                            daily = DailySiteReading.objects.filter(
                                associated_Site=site,
                                leg_id__in=all_leg_id,
                                reading_for__year=month.year,
                                reading_for__month=month.month,
                                reading_for__gte=baseline_date,
                                reading_for__lte=current,
                                is_visible=True
                            )

                            if daily.exists():
                                for j in daily:
                                    energyConsumed += j.unit_consumption
                                    energySaved += j.daily_baseline_value
                                    if carbon_visible:
                                        carbon_saved = energySaved * carbon_emission_value

                    energySaved = energySaved - energyConsumed

                    try:
                        percentage_saved = round(
                            energySaved * 100 / (energySaved + energyConsumed), 1
                        )
                    except:
                        percentage_saved = 0.0

                    energy_consumed_list.append(round(energyConsumed, 1))
                    energy_saved_list.append(round(energySaved, 1))
                    carbon_list.append(round(carbon_saved, 1))
                    percentage_saved_list.append(percentage_saved)

            # 🔴 CACHE ONLY PREVIOUS 11 MONTHS
            cache_data = {
                "months": month_list[:-1],
                "energyConsumed": energy_consumed_list[:-1],
                "energySaved": energy_saved_list[:-1],
                "carbon_saved": carbon_list[:-1],
                "percentageSaved": percentage_saved_list[:-1]
            }

            cache.set(cache_key, cache_data, timeout=60 * 60 * 24 * 90)

            return Response({
                "result": 1,
                "months": month_list,
                "energySaved": energy_saved_list,
                "energyConsumed": energy_consumed_list,
                "carbon_saved": carbon_list,
                "percentageSaved": percentage_saved_list
            })
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})

class EnergySavingsHourlyBarChartOld(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        print("function start time is : ", start_time)
        site = Site.objects.get(id=site_id)
        # return Response({"status":200, "msg":"working fine"})
        date = data.get("date", '')
        date = datetime.strptime(date, "%Y/%m/%d")
        print("date ::", date)
        print("ii", date.date())
        hourList = []
        dataList = []
        savingList = []
        all_leg_id = DailySiteReading.objects.filter(associated_Site=site, reading_for=date.date()).distinct("leg_id")
        print("all leg ids", all_leg_id)
        print("length : ", len(all_leg_id))
        oneDayData = HourlySiteReading.objects.filter(associated_Site=site_id, reading_from__date=date.date(),
                                                      is_visible=True)
        for leg in all_leg_id:
            aisle_name = AisleGroup.objects.filter(site=site_id, attached_leg_id=leg.leg_id)
            if aisle_name.exists():
                name = aisle_name[0].aisleGroupName
            else:
                name = leg.leg_id
            print('leg :', leg)
            unitConsumptionList = []
            savingConsumptionList = []
            hourList = []
            for i in range(24):
                current_hour = i
                print("current_hour", current_hour)
                if current_hour <= 9:
                    hr = '0' + str(current_hour) + ':00'
                else:
                    hr = str(current_hour) + ':00'
                hourList.append(hr)
                unit_consumption = 0.0
                energy_saved = 0.0
                if aisle_name.exists():
                    hourly = oneDayData.filter(aisle_group=aisle_name[0], reading_from__hour=current_hour)
                else:
                    hourly = oneDayData.filter(leg_id=leg, reading_from__hour=current_hour)
                print('hourly data', hourly)
                if hourly.exists():
                    for j in hourly:
                        try:
                            unit_consumption += j.unit_consumption
                            energy_saved += j.energy_saved
                        except Exception as e:
                            print("exception", e)
                unitConsumptionList.append(round(unit_consumption, 2))
                savingConsumptionList.append(round(energy_saved, 2))
            print("unit data: ", unitConsumptionList)
            # aisle_name = AisleGroup.objects.filter(site=site_id, attached_leg_id=leg.leg_id)
            # if aisle_name.exists():
            #     name = aisle_name[0].aisleGroupName
            # else:
            #     name = leg.leg_id
            dataList.append({"name": name, "data": unitConsumptionList, "type": 'column'})
            savingList.append({"name": name, "data": savingConsumptionList, 'type': 'column'})
        if site.is_live:
            baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
            print("checking for baseline has been saved or not: ", baseline)
            baselineList = []
            if baseline.exists():
                print("baseline of site is there: ", baseline)
                for i in range(24):
                    current_hour = i
                    if current_hour <= 9:
                        hr = '0' + str(current_hour) + ':00'
                    else:
                        hr = str(current_hour) + ':00'
                    hourList.append(hr)

                    print("hour inside baseline calculation", current_hour)
                    try:
                        baseline_value = HourlySiteReading.objects.filter(associated_Site=site,
                                                                          reading_from__hour=current_hour,
                                                                          is_visible=True)
                        print("checking the baseline value for particular hour")
                        if baseline_value.exists():
                            print('baseline exists for that hour', baseline_value)
                            baseline_data = 0.0
                            for j in baseline_value:
                                baseline_data += j.hourly_baseline_value
                                print("baseline_data: ", baseline_data)
                            print('total baseline of all legs', baseline_data)
                            baselineList.append(baseline_data)
                        else:
                            print("baseline doesn't exists for that hour. Sending 0.0 value", baseline_value)
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                    except Exception as e:
                        print('Exception EnergySavingsHourlyBarChart is', e)
                        baseline_value = 0.0
                        baselineList.append(baseline_value)
            dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
        end_time = datetime.now()
        print("function end time is : ", end_time)
        time_taken = end_time - start_time
        print("time_taken", time_taken)
        hourList = ["00:00", "01:00", "02:00", "03:00", "04:00", "05:00", "06:00", "07:00", "08:00", "09:00", "10:00",
                    "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00",
                    "22:00", "23:00"]
        return Response({"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList})


class EnergySavingsHourlyBarChart(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        print("function start time is: ", start_time)
        site = Site.objects.get(id=site_id)
        date = datetime.strptime(data.get("date", ''), "%Y/%m/%d")
        hourList = ["{:02d}:00".format(i) for i in range(24)]
        dataList = []
        savingList = []
        oneDayData = HourlySiteReading.objects.filter(associated_Site=site_id, reading_from__date=date.date(),
                                                      is_visible=True)
        aisle_names = AisleGroup.objects.filter(site=site_id)
        for aisle in  aisle_names:
            leg_id = aisle.attached_leg_id
            aisle_name = aisle.aisleGroupName
            unitConsumptionList = []
            savingConsumptionList = []
            hourly_data = oneDayData.filter(Q(leg_id=leg_id)).values(
                "reading_from__hour").annotate(unit_consumption_sum=Sum("unit_consumption"),
                                               energy_saved_sum=Sum("energy_saved"))
            hourly_data_dict = {reading["reading_from__hour"]: reading for reading in hourly_data}

            for i in range(24):
                hourly = hourly_data_dict.get(i)
                unit_consumption = round(hourly["unit_consumption_sum"], 2) if hourly else 0.0
                energy_saved = hourly["energy_saved_sum"] if hourly else 0.0
                unitConsumptionList.append(unit_consumption)
                savingConsumptionList.append(energy_saved)
            dataList.append({"name": aisle_name, "data": unitConsumptionList, "type": "column"})
            savingList.append({"name": aisle_name, "data": savingConsumptionList, "type": "column"})
        if site.is_live:
            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site).exclude(
                Q(baseline_to__isnull=False)).aggregate(
                Sum('baseline_value'))
            latest_baseline_value = latest_baseline_value['baseline_value__sum']
            if datetime.now().date() == date.date() and latest_baseline_value is not None:
                baselineList = [round(latest_baseline_value/24, 2) for i in range(24)]
            else:
                previousDateDailyBaselineValue = DailySiteReading.objects.filter(associated_Site=site, reading_for=date.date()).aggregate(Sum('daily_baseline_value'))
                previousDateHourlyBaselineValue = previousDateDailyBaselineValue['daily_baseline_value__sum']
                if previousDateHourlyBaselineValue is not None:
                    baselineList = [round(previousDateHourlyBaselineValue/24, 2) for i in range(24)]
                else:
                    baselineList = [0 for i in range(24)]
            dataList.append({"name": "baseline", "data": baselineList, "type": "spline"})
        end_time = datetime.now()
        print("function end time is: ", end_time)
        time_taken = end_time - start_time
        print("time_taken", time_taken)
        return Response({"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList})




class EnergySavingsHourlyBarChartV2(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        print("function start time is:", start_time)

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"result": 0, "msg": "Site not found"}, status=404)

        date_str = data.get("date", "")
        try:
            date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response({"result": 0, "msg": "Invalid date format"}, status=400)

        hourList = ["{:02d}:00".format(i) for i in range(24)]
        dataList = []
        savingList = []

        all_leg_ids = DailySiteReading.objects.filter(
            associated_Site=site, reading_for=date
        ).values_list("leg_id", flat=True).distinct()
        print(all_leg_ids)
        oneDayData = HourlySiteReading.objects.filter(
            associated_Site=site_id, reading_from__date=date, is_visible=True
        ).select_related('aisle_group')
        print(oneDayData)
        # Group by leg_id and hour to reduce the number of iterations
        hourly_data_map = {
            (item.leg_id, item.reading_from.hour): item
            for item in oneDayData
        }
        print(hourly_data_map)

        for leg_id in all_leg_ids:
            aisle_name_obj = AisleGroup.objects.filter(site=site_id, attached_leg_id=leg_id).first()
            name = aisle_name_obj.aisleGroupName if aisle_name_obj else leg_id
            print("name is",name)
            unitConsumptionList = []
            savingConsumptionList = []

            for i in range(24):
                unit_consumption = 0.0
                energy_saved = 0.0
                hourly_data = hourly_data_map.get((leg_id, i))

                if hourly_data:
                    unit_consumption = hourly_data.unit_consumption
                    energy_saved = hourly_data.energy_saved

                unitConsumptionList.append(round(unit_consumption, 2))
                savingConsumptionList.append(round(energy_saved, 2))

            dataList.append({"name": name, "data": unitConsumptionList, "type": 'column'})
            savingList.append({"name": name, "data": savingConsumptionList, 'type': 'column'})

        if site.is_live:
            latest_baseline = SiteBaseline.objects.filter(
                                associated_site_id=site_id).exclude(Q(baseline_to__isnull=False)).aggregate(Sum('baseline_value'))['baseline_value__sum']

            if datetime.now().date() == date.date() and latest_baseline is not None:
                baseline_list = [round(latest_baseline / 24, 2)] * 24
            else:
                previous_baseline = DailySiteReading.objects.filter(
                associated_Site=site,
                reading_for=date.date()
                ).aggregate(Sum('daily_baseline_value'))['daily_baseline_value__sum']

                baseline_list = [round(previous_baseline / 24, 2)] * 24 if previous_baseline is not None else [0] * 24

            dataList.append({"name": "baseline", "data": baseline_list, "type": "spline"})

        #if site.is_live:
        #    baseline_values = HourlySiteReading.objects.filter(
        #        associated_Site=site, reading_from__date=date, is_visible=True
        #    ).values('reading_from__hour').annotate(baseline_data=Sum('hourly_baseline_value')).order_by('reading_from__hour')

         #   baselineList = [baseline['baseline_data'] for baseline in baseline_values]
         #   dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})

        end_time = datetime.now()
        print("function end time is:", end_time)
        time_taken = end_time - start_time
        print("time_taken:", time_taken)

        return Response({"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList})








class BaselineHistory(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("baseline history data", data)
        site_id = data.get('site_id', '')
        dataList = []
        dateList = []
        all_leg_id = SiteBaseline.objects.distinct('leg_id').filter(associated_site_id=site_id)
        print("hii")
        for i in all_leg_id:
            leg_id = i.leg_id
            data = []
            for j in SiteBaseline.objects.filter(associated_site_id=site_id, leg_id=leg_id).order_by('baseline_from'):
                baseline_value = j.baseline_value
                baseline_from = j.baseline_from
                baseline_from = datetime.strftime(baseline_from, "%Y/%m/%d")
                dateList.append(baseline_from)
                data.append(round(baseline_value, 2))
            aisle_name = AisleGroup.objects.filter(site=site_id, attached_leg_id=leg_id)
            if aisle_name.exists():
                name = aisle_name[0].aisleGroupName
            else:
                name = leg_id
            dataList.append({"name": name, "data": data})
        print("dataList", dataList)
        print("dateList", list(set(dateList)))
        return Response({'result': 1, "Data": dataList, "Dates": dateList})


class BaselineData(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data", data)
        site_id = data.get('site_id', '')
        date = data.get('date', '')
        date = datetime.strptime(date, '%Y/%m/%d')
        DataList = []
        print("above all leg")
        all_leg = AisleGroup.objects.distinct('aisleGroupName').filter(site_id=site_id)
        print("all leg data :", all_leg)
        for i in all_leg:
            print('leg is', i)
            aisle_info = AisleGroup.objects.filter(site_id=int(site_id), aisleGroupName=i.aisleGroupName)[0]
            print("aisle info: ", aisle_info)
            current_consumption = DailySiteReading.objects.filter(associated_Site=site_id, leg_id=i.attached_leg_id,
                                                                  reading_for=date)
            print("current consumption data: ", current_consumption)
            consumption = 0.0
            if current_consumption.exists():
                consumption += current_consumption[0].unit_consumption
            print('consumption', consumption)
            data = {"aisle_name": aisle_info.aisleGroupName, 'total_lights': aisle_info.total_lights,
                    'expected_consumption': aisle_info.expected_consumption,
                    'current_consumption': round(consumption, 2)}
            DataList.append(data)
        return Response({"result": 1, "data": DataList})


class SavingBaselineData(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data of saving baseline", data)
        site_id = data.get('siteId', '')
        leg_id = data.get('legId', '')
        baseline_value = data.get('baselineValue', '')
        date = data.get('date', '')
        date = datetime.strptime(date, '%Y/%m/%d')
        site = Site.objects.get(id=site_id)
        print("site instance", site)
        aisle = AisleGroup.objects.filter(site_id=int(site_id), aisleGroupName=leg_id)[0]
        print("aisle group is:", aisle)
        baseline_data = SiteBaseline.objects.filter(associated_site_id=site_id, aisle_group=aisle)
        print("baseline data", baseline_data)
        if baseline_data.exists():
            change_date = date - timedelta(days=1)
            update_field = \
                SiteBaseline.objects.filter(associated_site_id=site, aisle_group=aisle).order_by('-baseline_from')[0]
            print("$$$$$, ", update_field.baseline_from)
            print("date", date)
            print("######", update_field)
            if update_field.baseline_from == date.date():
                print("inside if ")
                update_field.baseline_value = baseline_value
                print("@@@@@@@ ", update_field)
                update_field.save()
            else:
                print("inside else")
                update_field.baseline_to = change_date
                update_field.save()
                print("updated field :", update_field)
                baseline = SiteBaseline.objects.create(associated_site_id=site, aisle_group=aisle,
                                                       leg_id=baseline_data[0].leg_id,
                                                       baseline_value=baseline_value,
                                                       baseline_from=date.date())
                print("baseline value created :", baseline)
            current_consumption = DailySiteReading.objects.filter(associated_Site=site_id,
                                                                  leg_id=baseline_data[0].leg_id,
                                                                  reading_for=date.date()).update(daily_baseline_value=baseline_value)

            print('daily table unit consumption updated', current_consumption)
            aisle_group = AisleGroup.objects.distinct('aisleGroupName').filter(site_id=site_id).exclude(
                aisleGroupName=leg_id)
            print("all aisle groups", aisle_group)
            for i in aisle_group:
                b = SiteBaseline.objects.filter(associated_site_id=site, leg_id=i.id).order_by("-baseline_from")[0]
                if b.baseline_from != date.date():
                    previous_baseline_value = b.baseline_value
                    b.baseline_to = change_date
                    b.save()
                    new_entry = SiteBaseline.objects.create(associated_site_id=site, leg_id=i.id, aisle_group=i,
                                                            baseline_value=previous_baseline_value, baseline_from=date)
                    print("new entry is", new_entry)
                else:
                    pass
        else:
            print("baseline going to saved")
            baseline = SiteBaseline.objects.create(associated_site_id=site, aisle_group=aisle, leg_id=aisle.id,
                                                   baseline_value=baseline_value,
                                                   baseline_from=date)
            print("baseline value created :", baseline)
            current_consumption = DailySiteReading.objects.filter(
                associated_Site=site_id, leg_id=baseline_data[0].leg_id, reading_for=date).update(
                daily_baseline_value=baseline_value)
            # current_consumption.unit_consumption = baseline_value
            # current_consumption.save()
            print('daily table unit consumption updated', current_consumption)
        return Response({'result': 1, 'msg': 'baseline value set'})


class AisleLevelBaseline(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", '')
        site = Site.objects.get(id=site_id)
        from_date = data.get("from_date", '')
        till_date = data.get("till_date", '')
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        currentDate = datetime.now()
        dateList = []
        dataList = []
        if tillDate.month == currentDate.month:
            all_leg_id = DailySiteReading.objects.distinct('leg_id').filter(associated_Site=site)
            for leg in all_leg_id:
                baseline = []
                dateList = []
                for i in range(30):
                    date = currentDate - timedelta(days=29 - i)
                    dateList.append(date.date())
                    daily = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, reading_for=date)
                    baseline_value = 0.0
                    if daily.exists():
                        for j in daily:
                            baseline_value += j.baseline_value
                    baseline.append(baseline_value)
                dataList.append({"name": leg.leg_id, "data": baseline, 'type': 'column'})
        else:
            total_days = (tillDate.day - fromDate.day) + 1
            all_leg_id = DailySiteReading.objects.distinct('leg_id').filter(associated_Site=site)
            for leg in all_leg_id:
                baseline = []
                dateList = []
                for i in range(0, total_days):
                    date = currentDate - timedelta(days=i)
                    dateList.append(date.date())
                    daily = DailySiteReading.objects.filter(associated_Site=site, leg_id=leg, reading_for=date)
                    baseline_value = 0.0
                    if daily.exists():
                        for j in daily:
                            baseline_value += j.baseline_value
                    baseline.append(baseline_value)
                dataList.append({"name": leg.leg_id, "data": baseline, 'type': 'column'})
        return Response({"result": 1, "Dates": dateList, "Data": dataList})


class TotalAlarmsOnSitePageTabularForm(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data in alarm table", data)
        site_id = data.get("site_id", '')
        print("site did ", site_id)
        site = Site.objects.get(id=site_id)
        print("site details ", site)
        customer = site.customer
        alarms = AlarmNotifications.objects.filter(created_by=customer, site_id=site, user_level=4)
        print("alarms: ", alarms)
        data_list = []
        for i in alarms:
            print("inside the loop!!", i)
            alarm_type = i.get_Alarm_type_display()
            print("alarm type: ", alarm_type)
            object_type = i.get_object_type_display()
            print("object type: ", object_type)
            object_name = i.object_id
            print("object name: ", object_name)
            created_time = i.created_time
            print("created time: ", created_time)
            created_time = datetime.strftime(created_time, "%d-%m-%Y")
            alarm_priority = i.get_Alarm_priority_display()
            print("alarm priority: ", alarm_priority)
            data_list.append({
                "alarm_type": alarm_type,
                "object_type": object_type,
                "object_name": object_name,
                "alarm_priority": alarm_priority,
                "created_date": created_time
            })
        print("data list: ", data_list)
        return Response({"result": 1, "data": data_list, "msg": "Alarms details on site page"})


class SiteApiBasedOnSiteType(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data is: ", data)
        customer_id = data.get("customer_id")
        site_id = data.get("site_id", "")
        site = Site.objects.get(id=site_id)
        site_type = site.site_type
        print("site type: ", site_type)
        data_list = []
        if site_type == 1:
            print("current site is metering. so send all sites of saving")
            sites = Site.objects.filter(customer=customer_id, site_type=2)
            for i in sites:
                data_list.append({"id": i.id, "site_name": i.site_name, "site_type": i.site_type})
            print("all sites are: ", sites)
        elif site_type == 2:
            print("current site is saving. so send all sites of metering")
            sites = Site.objects.filter(customer=customer_id, site_type=1)
            print("all sites are: ", sites)
            for i in sites:
                data_list.append({"id": i.id, "site_name": i.site_name, "site_type": i.site_type})
        return Response({"result": 1, "data": data_list})


class FetchAllCustomers(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request):
        header = request.META.get("HTTP_AUTHORIZATION")
        customers = User.objects.filter(UserType=4)
        customer_data_list = []
        if customers.exists():
            for i in customers:
                customer_data_list.append({"id": i.id, "username": i.username, "email": i.email})
        return Response({"status": 200, "msg": "customer details", "data": customer_data_list})


class CreateCustomerUsingProvisioning(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            username = data.get("customer_name")
            password = "Aviconn@123#"
            customer_type = 4
            email = data.get("customer_email")
            contact = data.get("customer_contact")
            currentdate = datetime.now()
            user = User.objects.create(username=username, password=make_password(password), email=email,
                                       Contact_number=contact, UserType=customer_type)

            if user:
                customer = CustomerInfo.objects.create(customer=user)
                return Response({"status": 200, "msg": "user created", "user_id": user.id})
            return Response({"status": 400, "msg": "unable to create user"})
        except Exception as err:
            print("error", err)
            return Response({"status": 500, "msg": "server error", "error": err.__class__.__name__})


class CreateSiteUsingProvisioning(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        sitename = data.get("site_name")
        sitetype = data.get("site_type")
        location = data.get("site_location")
        customer_id = data.get("customer_id")
        customer = User.objects.get(id=customer_id)
        site = Site.objects.create(customer=customer, site_name=sitename,
                                   site_type=sitetype, location=location, live_date=datetime.now())

        if site:
            return Response({"status": 200, "msg": "site created successfully", "site_id": site.id})
        return Response({"status": 500, "msg": "unable to create site"})


class FetchAllSitesForProvisoning(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request):
        all_sites = Site.objects.all()
        site_list = []
        for i in all_sites:
            site_list.append({
                "id": i.id, 
                "site_name": i.site_name, 
                "location": i.location,
                "site_type": i.site_type,
                "customer_id": i.customer_id  # Add this line
            })
        return Response({"status": 200, "data": site_list})

class CreateAisleGroupUsingProvisioning(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        try:
            data = request.data
            aisle_name = data.get("aisle_name")
            site_id = data.get("site_id")
            site_type = data.get("site_type")
            site = Site.objects.get(id=site_id)
            if site_type == 1:
                power_source = data.get("power_source")
                aisle_group = AisleGroup.objects.create(site=site, aisleGroupName=aisle_name,
                                                        is_this_power_source=True, power_source=power_source)
            else:
                aisle_group = AisleGroup.objects.create(site=site, aisleGroupName=aisle_name)
            return Response({"status": 200, "msg": "aisle group created successfully", "aisle_id": aisle_group.id})
        except Exception as err:
            return Response({"status": 500, "msg": "internal server error", "error": err.__class__.__name__})


class CreateHomeGatewayIdUsingProvisioning(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        try:
            data = request.data
            print("data : ", data)
            home_gateway_name = data.get("home_gateway_name")
            rssh_port = data.get("rssh_port")
            monitoring_port = data.get("monitoring_port")
            site_id = data.get("site_id")
            site = Site.objects.get(id=site_id)
            homeGateway = HomeGatewayId.objects.create(connected_to=site, hgw_id=home_gateway_name,
                                                       rssh_port=rssh_port, monitoring_port=monitoring_port)
            print("homeGateway", homeGateway)
            if homeGateway:
                return Response({"status": 200, "msg": "home gateway id created successfully"})
        except Exception as err:
            print("error : ", err)
            return Response({"status": 500, "msg": "internal server error", "error": err.__class__.__name__})


class FetchAisleGroupsForParticularSiteUsingProvisioning(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")
            aisle_groups = AisleGroup.objects.filter(site_id=site_id).values()
            return Response({"status": 200,"data": list(aisle_groups)})
        except Exception as err:
            return Response({"status": 500, "error": err.__class__.__name__})

class FetchHGID(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            site_id = request.query_params.get('site_id')
            
            if not site_id:
                return Response({"status": 400, "msg": "site_id is required"})
            
            h = HomeGatewayId.objects.filter(connected_to=site_id)
            
            res = [
                {
                    "id": i.id,
                    "hgw_id": i.hgw_id,
                    "rssh_port": i.rssh_port,
                    "monitoring_port": i.monitoring_port,
                }
                for i in h
            ]
            
            response_data = {
                "status": 200,
                "site_id": site_id,
                "home_gateways": res,
            }
            
            return Response(response_data)
        
        except Exception as e:
            return Response({"status": 500, "msg": str(e)})


class FetchParticularCustomerUsingProvisioningScript(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        customer_id = data.get("id", "")
        customer = User.objects.get(id=customer_id)
        return Response({"status": 200, "username": customer.username, "email": customer.email,
                         "contact": customer.Contact_number})


class FetchLastRsshPort(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request):
        rssh_port = HomeGatewayId.objects.all().order_by('-id')[0]
        return Response({"status": 200, "rssh_port": rssh_port.rssh_port})


class FireAlarm(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data : ", data)
        site_id = data.get('site_id', '')
        site = Site.objects.get(id=site_id)
        print("site : ", site)
        all_leg = AisleGroup.objects.distinct('aisleGroupName').filter(site=site)
        print("all_leg", all_leg)
        systemlist = []
        for i in all_leg:
            aisles = AisleGroup.objects.filter(site=site, aisleGroupName=i.aisleGroupName)
            print("aisles", aisles)
            firealarm = FirePumpAlarm.objects.filter(Site=site, aisleGroup__in=aisles)
            print("firealarm:", firealarm)
            if firealarm.exists:
                for j in firealarm:
                    systemlist.append(
                        {'aislename': j.aisleGroup.aisleGroupName, 'R_Voltage': j.r_volt, 'Y_Voltage': j.y_volt,
                         'B_Voltage': j.b_volt,
                         'current_date': j.Updated_on, "manual_time": j.manual_mode_updated_time,
                         "auto_mode": j.auto_mode_updated_time, "off_mode": j.off_mode_time,
                         "motor_status": j.motor_status, "motor_status_time": j.motor_status_time})
        return Response({"status": 200, "data": systemlist})


# class EmailHistory(APIView):
#     @entryExit
#     def post(self, request):
#         data = request.data
#         print("data : ", data)
#         site_id = data.get('site_id', '')
#         site = Site.objects.get(id=site_id)
#         print("site : ", site)
#         all_leg = AisleGroup.objects.distinct('aisleGroupName').filter(site=site)
#         print("all_leg", all_leg)
#         email_list = []
#         for i in all_leg:
#             aisles = AisleGroup.objects.filter(site=site, aisleGroupName=i.aisleGroupName)
#             print("aisles", aisles)
#             emailhistory = Email_History.objects.filter(fire_site=site, deviceName__in=aisles).order_by('-created')
#             for j in emailhistory:
#                 email_list.append({"site": j.fire_site.site_name, "device_name": j.deviceName.aisleGroupName,
#                                    "email_for": j.email_for, "datetime": j.created})
#         email_list = sorted(email_list, key=lambda x: x["datetime"], reverse=True)
#         return Response({"status": 200, "data": email_list})

class EmailHistory(APIView):

    @entryExit
    def post(self, request):
        site_id = request.data.get("site_id")

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"status": 404, "message": "Site not found"})

        emailhistory = (
            Email_History.objects
            .filter(fire_site=site)
            .select_related("fire_site", "deviceName")
            .order_by("-created")
        )

        email_list = [
            {
                "site": e.fire_site.site_name,
                "device_name": e.deviceName.aisleGroupName,
                "email_for": e.email_for,
                "datetime": e.created,
            }
            for e in emailhistory
        ]

        return Response({"status": 200, "data": email_list})


class FireEquipmentSystemAdd(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data", data)
        device_id = (data.get('id', ''))
        deviceName = data.get('deviceName')
        id = int(data.get('row_id'))
        assetno = data.get('assetNo', '')
        model_no = data.get('modelNo', '')
        loaction = data.get('location', '')
        updatedby = data.get('updated_by', '')
        warrenty_till = data.get('warrenty', '')
        last_service = data.get('last_service', '')
        next_service = data.get('next_service', '')
        fire = FireEquipmentsSystemType.objects.get(id=id)
        try:
            if device_id != "":
                msg = "record update"
                FireEquipmentsSystem.objects.filter(id=int(device_id)).update(deviceType=fire, assetNo=assetno,
                                                                              updatedBy=updatedby, modelNo=model_no,
                                                                              loaction=loaction,
                                                                              Warrenty_till=datetime.strptime(
                                                                                  warrenty_till, '%Y-%m-%d').date(),
                                                                              last_service=datetime.strptime(
                                                                                  last_service, '%Y-%m-%d').date(),
                                                                              next_service=datetime.strptime(
                                                                                  next_service, '%Y-%m-%d').date())
            else:
                msg = "record saved"
                firesystem = FireEquipmentsSystem.objects.create(deviceType=fire, assetNo=assetno, updatedBy=updatedby,
                                                                 modelNo=model_no, loaction=loaction,
                                                                 Warrenty_till=datetime.strptime(warrenty_till,
                                                                                                 '%Y-%m-%d').date(),
                                                                 last_service=datetime.strptime(last_service,
                                                                                                '%Y-%m-%d').date(),
                                                                 next_service=datetime.strptime(next_service,
                                                                                                '%Y-%m-%d').date())
            return Response({"status": 200, "msg": msg})
        except Exception as err:
            return Response({"status": 500})


class FireEquipmentSystemFetch(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data : ", data)
        row_id = data.get('row_id', '')
        fireEquipments = FireEquipmentsSystemType.objects.filter(id=row_id)
        print("fireEquipments", fireEquipments)
        fire = FireEquipmentsSystem.objects.filter(deviceType__in=fireEquipments)
        print("fire:", fire)
        data_list = []
        for i in fire:
            data_list.append(
                {"id": i.id, "updatedby": i.updatedBy, "deviceName": i.deviceType.devicename, "assetNo": i.assetNo,
                 "modelsNo": i.modelNo,
                 "location": i.loaction, "warrentDate": i.Warrenty_till, "last_serviceDate": i.last_service,
                 "next_serviceDate": i.next_service})
        return Response({"result": 1, "data": data_list})


class FireEquiSystemTypefetch(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data :", data)
        site_id = data.get('site_id', '')
        site = Site.objects.get(id=site_id)
        print("site : ", site)
        fireequipment = FireEquipmentsSystemType.objects.filter(site=site)
        print("fireequipment", fireequipment)
        list = []
        for i in fireequipment:
            list.append({"row_id": i.id, "deviceName": i.devicename, "categories": i.categories})
        return Response({"result": 1, "data": list})


class FireEquiSystemTypeAdd(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data:", data)
        devicename = data.get('deviceName', '')
        category = data.get('category', '')
        site = Site.objects.get(id=23)
        firesystem = FireEquipmentsSystemType(site=site, devicename=devicename, categories=category)
        firesystem.save()
        return Response("Data saved sucessfully")


class SnapshotApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", '')
        current_date = datetime.now()
        date = current_date.date()
        totalDevices = FireEquipmentsSystem.objects.all().count()
        t = FireEquipmentsSystem.objects.all()
        print("totalDevices", totalDevices)
        expiredDevice = FireEquipmentsSystem.objects.filter(next_service__lte=date).count()
        warrentyDeviceList = []
        warrenty = FireEquipmentsSystem.objects.filter(Warrenty_till__lte=date).count()
        print("warrenty : ", warrenty)
        warrentyDevices = FireEquipmentsSystem.objects.filter(Warrenty_till__lte=date)
        for i in warrentyDevices:
            warrentyDeviceList.append(
                {"id": i.id, "deviceName": i.deviceType.devicename, "assetNo": i.assetNo, "modelsNo": i.modelNo,
                 "location": i.loaction, "warrentDate": i.Warrenty_till, "last_serviceDate": i.last_service,
                 "next_serviceDate": i.next_service})
            # print("warrenty :",warrentyDeviceList)

        return Response({"status": 200, "totalDevices": totalDevices, "warrenty": warrenty,
                         "expiredDevice": expiredDevice, "data": warrentyDeviceList})


class ExpiredDevicesListApi(APIView):
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", '')
        current_date = datetime.now()
        date = current_date.date()
        list = []
        expiredDevice = FireEquipmentsSystem.objects.filter(next_service__lte=date)
        for i in expiredDevice:
            list.append({"id": i.id, "deviceName": i.deviceType.devicename, "modelsNo": i.modelNo, "assetNo": i.assetNo,
                         "location": i.loaction, "warrentDate": i.Warrenty_till, "last_serviceDate": i.last_service,
                         "next_serviceDate": i.next_service})
        return Response({"status": 200, "data": list})


class fireEquiSystemDelete(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        row = data.get("id")
        FireEquipmentsSystem.objects.filter(id=int(row)).delete()
        # site = Site.objects.get(id=23)
        # firesystem = FireEquipmentsSystem(id=row)
        # firesystem.delete()
        return Response({"status": 200, "msg": "Data deleted"})


class LightsDataApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        print("data :", data)
        data = LightsData.objects.all().order_by('-id')
        list = []
        for i in data:
            list.append({"areaName": i.areaName, "totalLights": i.totalLights, "18Watt": i.watt_18_Lights,
                         "20Watt": i.watt_20_Lights, "24Watt": i.watt_24_Lights, "36Watt": i.watt_36_Lights,
                         "40Watt": i.watt_40_Lights, "totalWattLights": i.totalWattLights, "totalUnits": i.totalUnits})
        return Response({"status": 200, "data": list})


class FansDataApi(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        data = FansData.objects.all().order_by('id')
        list = []
        for i in data:
            list.append({"areaName": i.areaName, "totalFans": i.totalFans, "80watt": i.watt_80_Lights,
                         "100watt": i.watt_100_Lights, "totalWattFans": i.totalWattFans, "totalUnits": i.totalUnits})
        return Response({"status": 200, "data": list})


'''class avgDataApi(APIView):
    def post(self, request):
        data = request.data
        print("data%%%%%%", data)
        site_id = data.get('siteId', '')
        from_date = data.get('from_date', '')
        print("from_date", from_date)
        till_date = data.get('till_date', '')
        fromDate = datetime.strptime(from_date, "%Y-%m-%d")
        print("fromDate", fromDate)
        tillDate = datetime.strptime(till_date, "%Y-%m-%d")
        site = Site.objects.get(id=site_id)
        days = (tillDate - fromDate)
        totaldays = days.days + 1
        print("Totaldays :", totaldays)
        energyConsumed = 0.0
        aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
        all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
        daily = DailySiteReading.objects.filter(associated_Site=site, reading_for__gte=fromDate,
                                                leg_id__in=all_leg_id, reading_for__lte=tillDate)
        print("daily : ", daily)
        if daily.exists():
            for i in daily:
                energyConsumed += i.unit_consumption
                avgData = round(energyConsumed / totaldays, 2)
        return Response(
            {"status": 200, "value": avgData, "energyConsumed": round(energyConsumed, 2), "totalDays": totaldays})'''


# class avgDataApi(APIView):
#     def post(self, request):
#         data = request.data
#         print("data%%%%%%", data)
#         site_id = data.get('siteId', '')
#         if int(site_id) == 34:
#             site_id = 29
#         from_date = data.get('from_date', '')
#         print("from_date", from_date)
#         till_date = data.get('till_date', '')
#         fromDate = datetime.strptime(from_date, "%Y-%m-%d")
#         print("fromDate", fromDate)
#         tillDate = datetime.strptime(till_date, "%Y-%m-%d")
#         site = Site.objects.get(id=site_id)
#         days = (tillDate - fromDate)
#         totaldays = days.days + 1
#         print("Totaldays :", totaldays)
#         energyConsumed = 0.0
#         if int(data.get('siteId')) == 34:
#             aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
#         else:
#             aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
#         all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
#         daily = DailySiteReading.objects.filter(associated_Site=site, reading_for__gte=fromDate,
#                                                 leg_id__in=all_leg_id, reading_for__lte=tillDate)
#         print("daily : ", daily)
#         if daily.exists():
#             for i in daily:
#                 energyConsumed += i.unit_consumption
#                 avgData = round(energyConsumed / totaldays, 2)
#         return Response(
#             {"status": 200, "value": avgData, "energyConsumed": round(energyConsumed, 2), "totalDays": totaldays})

class avgDataApi(APIView):
    def post(self, request):
        data = request.data
        print("data%%%%%%", data)
        
        # Get site_id with proper parameter name and validation
        site_id = data.get('site_id') or data.get('siteId', '')
        if not site_id:
            return Response({"status": 400, "error": "site_id is required"}, status=400)
        try:
            site_id = int(site_id)
        except (ValueError, TypeError):
            return Response({"status": 400, "error": "site_id must be a valid integer"}, status=400)
            
        # Handle virtual site mapping
        if site_id == 34:
            site_id = 29
            
        from_date = data.get('from_date', '')
        till_date = data.get('till_date', '')
        
        if not from_date or not till_date:
            return Response({"status": 400, "error": "from_date and till_date are required"}, status=400)
            
        print("from_date", from_date)
        
        try:
            fromDate = datetime.strptime(from_date, "%Y-%m-%d")
            tillDate = datetime.strptime(till_date, "%Y-%m-%d")
        except ValueError as e:
            return Response({"status": 400, "error": f"Invalid date format: {str(e)}"}, status=400)
            
        print("fromDate", fromDate)
        
        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"status": 404, "error": f"Site with id {site_id} not found"}, status=404)
            
        days = (tillDate - fromDate)
        totaldays = days.days + 1
        print("Totaldays :", totaldays)
        energyConsumed = 0.0
        avgData = 0.0
        
        # Use the validated site_id for virtual site mapping
        original_site_id = data.get('site_id') or data.get('siteId', '')
        if int(original_site_id) == 34:
            aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
        else:
            aisle_group = AisleGroup.objects.filter(virtual_siteID=site_id, is_visible=True)
        all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
        daily = DailySiteReading.objects.filter(aisle_group__virtual_siteID=site, reading_for__gte=fromDate,
                                                leg_id__in=all_leg_id, reading_for__lte=tillDate)
        print("daily : ", daily)
        if daily.exists():
            for i in daily:
                energyConsumed += i.unit_consumption
            avgData = round(energyConsumed / totaldays, 2)
        return Response(
            {"status": 200, "value": avgData, "energyConsumed": round(energyConsumed, 2), "totalDays": totaldays})


class DownloadExcel(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        print("data", data)
        site_id = data.get("site_id")
        if int(site_id) == 34:
            site_id = 29
        user_type = int(data.get("user_type", ''))
        print("user_type", user_type)
        start_date = data.get("from_date")
        fromDate = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = data.get("end_date")
        tillDate = datetime.strptime(end_date, "%Y-%m-%d")
        final_list = []
        first_row = ["Date", "TotalConsumption"]
        if user_type == 1:
            aisles = AisleGroup.objects.filter(site=site_id)
        else:
            if int(data.get("site_id", '')) == 34:
                aisles = AisleGroup.objects.filter(attached_leg_id__in=[259,276, 260, 261, 710])
            else:
                aisles = AisleGroup.objects.filter(site=site_id, is_visible=True)
        for i in aisles:
            first_row.append(i.aisleGroupName)
        final_list.extend([first_row])
        all_leg_id = [aisle.attached_leg_id for aisle in aisles]
        total_days = tillDate - fromDate
        total_days = total_days.days + 1
        for i in range(total_days):
            date = fromDate + timedelta(days=i)
            unit_consumption_array = [datetime.strftime(date, "%d-%b-%Y"), 0]
            site_consumption = 0
            for aisle in all_leg_id:
                daily = DailySiteReading.objects.filter(associated_Site=site_id, leg_id=aisle, reading_for=date)
                if daily.exists():
                    consumption = round(daily[0].unit_consumption, 2)
                else:
                    consumption = 0
                site_consumption += round(consumption, 2)
                unit_consumption_array.append(consumption)
            unit_consumption_array[1] = site_consumption
            final_list.extend([unit_consumption_array])

        df = pd.DataFrame(final_list)
        file_name = 'output.csv'
        # Set the return value of the HttpResponse
        response = HttpResponse(content_type='text/csv', )
        response['filename'] = file_name
        response['Content-Disposition'] = 'attachment; filename={}'.format(file_name)
        df.to_csv(response, index=False, header=False)
        return response


class LoadGrapghAPI(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            current_date = datetime.now()
            raw_data = RawLoadData.objects.filter(site=site_id, created__date=current_date.date(),
                                                  created__hour=current_date.hour)
            res = []
            for i in raw_data:
                load_data = i.load_data / 1000
                res.append(
                        {"x": int(i.epoch_time), "y": round(load_data, 3), "aisle_name" : i.aisle_group.aisleGroupName , "color": i.aisle_group.load_graph_color})
                # res.append({"x":x,"y":rand,"color":i.aisle_group.color})
            return Response({"status": 200, "data": sorted(res, key=lambda d: d['x'])})
        except Exception as err:
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGrapghAPITestingPurpose(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            current_date = datetime.now().replace(day=11, hour=16)
            raw_data = RawLoadData.objects.filter(site=site_id, created__date=current_date.date(),
                                                  created__hour=current_date.hour)
            res = []
            for i in raw_data:
                load_data = i.load_data / 1000
                res.append(
                    {"x": int(i.epoch_time), "y": round(load_data, 3), "color": i.aisle_group.load_graph_color})
                # res.append({"x":x,"y":rand,"color":i.aisle_group.color})
                # sorted(res, key=lambda d: d['x'])
            return Response({"status": 200, "data": sorted(res, key=lambda d: d['x'])})
        except Exception as err:
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForEverySecond(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            epoch_time = data.get("epoch_time")
            raw_data = RawLoadData.objects.using("secondary").filter(site=site_id, epoch_time__gt=epoch_time)
            res = []
            for i in raw_data:
                load_data = i.load_data / 1000
                res.append(
                    {"x": int(i.epoch_time), "y": round(load_data, 3), "color": i.aisle_group.load_graph_color})
                # resp.append({"x":x,"y":rand,"color":color})
            return Response({"status": 200, "data": res})
        except Exception as err:
            print("Error: ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForHourlyData(APIView):
    def post(self, request):
        data = request.data
        try:
            
            site_id = data.get("site_id")
            selected_date = data.get("date")
            selected_date = datetime.strptime(selected_date, "%Y/%m/%d")
            hourly_data = HourlyLoadData.objects.using("secondary").filter(site=site_id, created__date=selected_date.date()).order_by(
                "created")
            res = []
            if hourly_data.exists():
                for i in hourly_data:
                    load_data = i.load_data / 1000
                    res.append(
                            {"x": int(i.epoch_time), "y": round(load_data, 3), "color": i.aisle_group.load_graph_color, "aisle_name" : i.aisle_group.aisleGroupName})
            return Response({"status": 200, "data": res})
        except Exception as err:
            print("Error : ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForDailyData(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            selected_date = data.get("date")
            till_date = datetime.strptime(selected_date, "%Y/%m/%d")
            from_date = till_date - timedelta(days=31)
            hourly_data = DailyLoadData.objects.using("secondary").filter(site=site_id, created__date__gte=from_date.date(),
                                                       created__date__lte=till_date.date()).order_by("created")
            res = []
            if hourly_data.exists():
                for i in hourly_data:
                    load_data = i.load_data / 1000
                    res.append(
                        {"x": int(i.epoch_time), "y": round(load_data, 3), "color": i.aisle_group.load_graph_color, "aisle_name" : i.aisle_group.aisleGroupName})
            return Response({"status": 200, "data": res})
        except Exception as err:
            print("Error : ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadDataExcelDownload(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            date = data.get("date")
            selected_date = datetime.strptime(date, "%Y/%m/%d")
            graph_type = data.get("graph_type")
            date_array = []
            data_array = []
            power_source = []
            if graph_type == "0":
                # download hourly data
                final_data = HourlyLoadData.objects.filter(site=site_id, created__date=selected_date.date()).order_by(
                    "created")
            elif graph_type == "1" or graph_type == "2":
                # download daily data
                till_date = datetime.strptime(date, "%Y/%m/%d")
                from_date = till_date - timedelta(days=31)
                final_data = DailyLoadData.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                          created__date__lte=till_date.date()).order_by("created")
            elif graph_type == "3":
                # download daily data
                till_date = datetime.strptime(date, "%Y/%m/%d")
                from_date = till_date - timedelta(days=31)
                final_data = MainsDgLoadData.objects.filter(site=site_id,
                                                            created__date=till_date.date())
            elif graph_type == "4":
                date = datetime.now()
                final_data = RawLoadData.objects.filter(site=site_id, created__date=date.date(),
                                                        created__hour=date.hour).order_by("created")
            else:
                # download monthly data
                final_data = []
            if final_data:
                for i in final_data:
                    load_data = i.load_data / 1000
                    if load_data > 0:
                        date_array.append(i.created.strftime("%d %b, %Y %H:%M:%S"))
                        data_array.append(round(load_data, 3))
                        if graph_type == "3":
                            power_source.append(i.aisle_group.aisleGroupName)
                if graph_type == "3":
                    df = pd.DataFrame({"Date": date_array, "Load Data(KW)": data_array, "Power_Source": power_source})
                else:
                    df = pd.DataFrame({"Date": date_array, "Load Data(KW)": data_array})
                file_name = "load_data_{}".format(date)
                response = HttpResponse(content_type='text/csv', )
                response['filename'] = file_name
                response['Content-Disposition'] = 'attachment; filename={}'.format(file_name)
                df.to_csv(response, index=False)
                return response
            else:
                return Response({"status": 500, "data": [], "msg": "No data for selected graph and date"})
        except Exception as err:
            print(err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class FetchFluctuatedPowerFactor(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            pf = PowerFactorData.objects.filter(site=site_id)
            res = []
            if pf.exists():
                for i in pf:
                    r_phase = str(round(i.r_phase_pf, 3)) + " PF Not Ok" if i.r_phase_pf > 0 else "PF Normal"
                    y_phase = str(round(i.y_phase_pf, 3)) + " PF Not Ok" if i.y_phase_pf > 0 else "PF Normal"
                    b_phase = str(round(i.b_phase_pf, 3)) + " PF Not Ok" if i.b_phase_pf > 0 else "PF Normal"
                    res.append({"created": i.created.strftime("%d %b, %Y %H:%M:%S"), "power_source": i.supply_source,
                                "r_phase": r_phase,
                                "y_phase": y_phase, "b_phase": b_phase})
            return Response({"status": 200, "data": res})
        except Exception as err:
            print(err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class FetchMinMaxMonthlyLoadData(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("id")
            monthly_load_data = MonthlyMinMaxLoadData.objects.filter(site=site_id).order_by('created')
            res = []
            min = 100000
            max = 0
            min_date = ''
            max_date = ''
            if monthly_load_data.exists():
                for i in monthly_load_data:
                    if min > i.min_load:
                        min = i.min_load / 1000 if i.min_load else 0.0
                        min_date = i.created.strftime("%d %b, %Y %H:%M:%S")
                    if max < i.max_load:
                        max = i.max_load / 1000 if i.max_load else 0.0
                        max_date = i.created.strftime("%b %m %Y %H:%M:%S")
                    min_load = i.min_load / 1000
                    max_load = i.max_load / 1000
                    res.append({"created": i.created.strftime("%b %m %Y %H:%M:%S"), "power_source": i.supply_source,
                                "min_load": round(min_load, 3),
                                "min_load_created": i.min_load_created.strftime("%d %b, %Y %H:%M:%S"),
                                "max_load": round(max_load, 3),
                                "max_load_created": i.max_load_created.strftime("%d %b, %Y %H:%M:%S"),
                                "month": i.max_load_created.strftime("%b, %Y")})
                return Response({"status": 200, "data": res, "min_value": min, "min_date": min_date, "max_value": max,
                                 "max_date": max_date})
            return Response({"status": 500, "data": [], "msg": "No records exists"})
        except Exception as err:
            print(err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class DownloadMinMaxMonthlyLoadData(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            monthly_load_data = MonthlyMinMaxLoadData.objects.filter(site=site_id).order_by('created')
            power_source_array = []
            min_load_array = []
            min_load_date_array = []
            max_load_array = []
            max_load_date_array = []
            month_year = []
            if monthly_load_data.exists():
                for i in monthly_load_data:
                    min_load = i.min_load / 1000
                    max_load = i.max_load / 1000
                    power_source_array.append(i.supply_source)
                    min_load_array.append(round(min_load, 3))
                    min_load_date_array.append(i.min_load_created.strftime("%d %b, %Y %H:%M:%S"))
                    max_load_array.append(round(max_load, 3))
                    max_load_date_array.append(i.max_load_created.strftime("%d %b, %Y %H:%M:%S"))
                    month_year.append(i.max_load_created.strftime("%b, %Y"))
                df = pd.DataFrame({"PowerSource": power_source_array, "Min_Load_Value": min_load_array,
                                   "Min_Load_Date": min_load_date_array, "Max_Load_Value": max_load_array,
                                   "Max_Load Date": max_load_date_array, "month": month_year})
                file_name = "monthly_min_max_data"
                response = HttpResponse(content_type='text/csv', )
                response['filename'] = file_name
                response['Content-Disposition'] = 'attachment; filename={}'.format(file_name)
                df.to_csv(response)
                return response
            return Response({"status": 500, "data": [], "msg": "No records exists"})
        except Exception as err:
            print(err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class DownloadFluctuatedPowerFactor(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            pf = PowerFactorData.objects.filter(site=site_id)
            date_array = []
            r_phase_array = []
            y_phase_array = []
            b_phase_array = []
            power_source_array = []
            if pf.exists():
                for i in pf:
                    r_phase = str(round(i.r_phase_pf, 3)) + " PF Not Ok" if i.r_phase_pf > 0 else "PF Normal"
                    y_phase = str(round(i.y_phase_pf, 3)) + " PF Not Ok" if i.y_phase_pf > 0 else "PF Normal"
                    b_phase = str(round(i.b_phase_pf, 3)) + " PF Not Ok" if i.b_phase_pf > 0 else "PF Normal"
                    date_array.append(i.created.strftime("%d %b, %Y %H:%M:%S"))
                    r_phase_array.append(r_phase)
                    y_phase_array.append(y_phase)
                    b_phase_array.append(b_phase)
                    power_source_array.append(i.supply_source)
                df = pd.DataFrame({"Date": date_array, "PowerSource": power_source_array, "R-Phase": r_phase_array,
                                   "Y-Phase": y_phase_array, "B-Phase": b_phase_array})
                file_name = "pf_data"
                response = HttpResponse(content_type='text/csv', )
                response['filename'] = file_name
                response['Content-Disposition'] = 'attachment; filename={}'.format(file_name)
                df.to_csv(response)
                return response
            return Response({"status": 500, "data": []})
        except Exception as err:
            print(err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class LoadGraphApiForMainsDgDailyData(APIView):
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id", 37)
            selected_date = data.get("date")
            till_date = datetime.strptime(selected_date, "%Y/%m/%d")
            from_date = till_date - timedelta(days=31)
            all_aisles = AisleGroup.objects.filter(site=site_id).order_by("id")
            final_data = []
            for aisle in all_aisles:
                hourly_data = MainsDgLoadData.objects.using("secondary").filter(site=site_id, aisle_group=aisle.id,
                                                             created__date=till_date.date()).order_by("created")
                res = {"name": aisle.aisleGroupName}
                if hourly_data.exists():
                    res["data"] = []
                    for i in hourly_data:
                        load_data = i.load_data / 1000
                        res["data"].append(
                            {"x": int(i.epoch_time), "y": round(load_data, 3), "color": aisle.load_graph_color})
                final_data.append(res)
            return Response({"status": 200, "data": final_data})
        except Exception as err:
            print("Error : ", err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class FetchDGAlertData(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            DGAlertsData.objects.create(alert_data=data)
            return Response({"status": 200, "msg": "alert received"})
        except Exception as err:
            print(err)
            return Response({"status": 500, "msg": "error while receiving alerts, {}".format(err)})



class DgFuelConsumptionDataApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            date = data.get("date")
            selected_date = datetime.strptime(date, "%Y/%m/%d")
            final_data = []
            fuel_data = DgFuelConsumptionData.objects.filter(site=site_id, created__date=selected_date.date()).order_by(
                "created")
            for i in fuel_data:
                final_data.append({"x": int(i.epoch_time), "y": round(i.fuel_consumption, 2)})
            dg_data = DgUnitConsumption.objects.filter(site=site_id, created__date=selected_date.date())
            logger.debug(final_data)
            logger.debug(dg_data)
            print("dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: ", i)
                    dg_unit_data.append({"x": int(i.epoch_time), "y": round(i.unit_consumption, 2)})
                    if i.dg_fuel_consumption > 0:
                        dg_fuel_data.append({"x": int(i.epoch_time), "y": i.dg_fuel_consumption})
                        dg_unit_per_litre.append(
                            {"x": int(i.epoch_time), "y": round(i.unit_consumption / i.dg_fuel_consumption, 2)})
            # fuel_alerts = DGAlertsData.objects.all()
            refuel_data = []
            theft_data = []
            fuel_alerts = DGFuelAlertsData.objects.filter(site=site_id, created__date=selected_date.date()).order_by(
                "created")
            if fuel_alerts.exists():
                for i in fuel_alerts:
                    if i.alert_name == 'refuel':
                        refuel_data.append({'x': int(i.epoch_time) * 1000, 'y': i.fuel_consumption})
                    elif i.alert_name == 'theft':
                        theft_data.append({'x': int(i.epoch_time) * 1000, 'y': i.fuel_consumption})
            refuel_final_data = {"name": "Refuel", "data": refuel_data, "type": "column"}
            theft_final_data = {"name": "Fuel Drain", "data": theft_data, "type": "column"}
            dg_unit_final_data = {"name": "DG_Unit_Consumption", "data": dg_unit_data, "type": "column"}
            dg_fuel_final_data = {"name": "DG_Fuel_Consumed", "data": dg_fuel_data, "type": "column"}
            dg_unit_per_litre_data = {"name": "Dg_Unit_Per_Ltr", "data": dg_unit_per_litre, "type": "column"}
            return Response(
                {"status": 200, "data": final_data, "refuel_alert": refuel_final_data, "theft_alert": theft_final_data,
                 "dg_unit_data": dg_unit_final_data, "dg_fuel_data": dg_fuel_final_data,
                 "dg_unit_per_litre_data": dg_unit_per_litre_data})
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})


class DgFuelConsumptionDataCustomRangeApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            from_date = data.get("from_date")
            end_date = data.get("end_date")
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%Y-%m-%d")
            final_data = []
            fuel_data = DgFuelConsumptionData.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                             created__date__lte=end_date.date()).order_by("created")
            for i in fuel_data:
                final_data.append({"x": int(i.epoch_time), "y": round(i.fuel_consumption, 2)})
            dg_data = DgUnitConsumption.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                       created__date__lte=end_date.date())
            logger.debug(final_data)
            logger.debug(dg_data)
            print("dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: ", i)
                    dg_unit_data.append({"x": int(i.epoch_time), "y": round(i.unit_consumption, 2)})
                    if i.dg_fuel_consumption > 0:
                        dg_fuel_data.append({"x": int(i.epoch_time), "y": i.dg_fuel_consumption})
                        dg_unit_per_litre.append(
                            {"x": int(i.epoch_time), "y": round(i.unit_consumption / i.dg_fuel_consumption, 2)})
            refuel_data = []
            theft_data = []
            fuel_alerts = DGFuelAlertsData.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                          created__date__lte=end_date.date()).order_by("created")
            if fuel_alerts.exists():
                for i in fuel_alerts:
                    if i.alert_name == 'refuel':
                        refuel_data.append({'x': int(i.epoch_time) * 1000, 'y': i.fuel_consumption})
                    elif i.alert_name == 'theft':
                        theft_data.append({'x': int(i.epoch_time) * 1000, 'y': i.fuel_consumption})

            refuel_final_data = {"name": "Refuel", "data": refuel_data, "type": "column"}
            theft_final_data = {"name": "Fuel Drain", "data": theft_data, "type": "column"}
            dg_unit_final_data = {"name": "DG_Unit_Consumption", "data": dg_unit_data, "type": "column"}
            dg_fuel_final_data = {"name": "DG_Fuel_Consumed", "data": dg_fuel_data, "type": "column"}
            dg_unit_per_litre_data = {"name": "Dg_Unit_Per_Ltr", "data": dg_unit_per_litre, "type": "column"}
            return Response(
                {"status": 200, "data": final_data, "refuel_alert": refuel_final_data, "theft_alert": theft_final_data,
                 "dg_unit_data": dg_unit_final_data, "dg_fuel_data": dg_fuel_final_data,
                 "dg_unit_per_litre_data": dg_unit_per_litre_data})
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})


'''class DGFuelDataExcelExport(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")
            from_date = data.get("start_date")
            end_date = data.get("end_date")
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%Y-%m-%d")
            # dg fuel absolute data in litre start here
            fuel_absolute_data = []
            fuel_data = DgFuelConsumptionData.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                             created__date__lte=end_date.date()).order_by("-created")
            for i in fuel_data:
                date = i.created.date()
                date = datetime.strftime(date, "%d-%b-%Y")
                fuel_absolute_data.append({"Date": date, "Time": str(i.created.hour) + ":" + str(i.created.minute),
                                           "Fuel_Level": round(i.fuel_consumption, 2)})
            # dg fuel absolute data in litre ends here
            # dg unit consumption data starts here
            dg_data = DgUnitConsumption.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                       created__date__lte=end_date.date()).order_by('-created')
            logger.debug(dg_data)
            print("dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_unit_data = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    dg_start_date = i.dg_start_date.date()
                    dg_start_time = str(i.dg_start_date.hour) + ":" + str(i.dg_start_date.minute)
                    dg_end_date = i.dg_end_date.date()
                    dg_end_time = str(i.dg_end_date.hour) + ":" + str(i.dg_end_date.minute)
                    dg_unit = i.unit_consumption
                    dg_fuel = i.dg_fuel_consumption
                    dg_start_date = datetime.strftime(dg_start_date, "%d-%b-%Y")
                    dg_end_date = datetime.strftime(dg_end_date, "%d-%b-%Y")
                    # dg_unit_data.append({"x": int(i.epoch_time), "y": round(i.unit_consumption, 2)})
                    if i.dg_fuel_consumption > 0:
                        dg_fuel_unit_data.append({"Start_Date": dg_start_date, "Start_Time": dg_start_time,
                                                  "End_Date": dg_end_date, "End_Time": dg_end_time,
                                                  "DG_Fuel_Consumed(Litres)": dg_fuel,
                                                  "DG_Unit_Consumption(KWH)": dg_unit,
                                                  "DG_Unit_Per_Ltr": round(dg_unit / dg_fuel, 2)})
            # dg unit consumption data ends here
            # alert data for excel start here date = datetime.strftime(alert_timestamp.date(), "%d-%b-%Y")

            fuel_alerts = DGFuelAlertsData.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                          created__date__lte=end_date.date()).order_by("-created")
            refuel_theft_data = []
            if fuel_alerts.exists():
                for i in fuel_alerts:
                    alert_timestamp = i.created
                    date = datetime.strftime(alert_timestamp.date(), "%d-%b-%Y")
                    if i.alert_name == 'refuel':
                        refuel_theft_data.append(
                            {"Date": date, "Time": str(alert_timestamp.hour) + ":" + str(alert_timestamp.minute),
                             "Activity": "Refuel", "Fuel(in Litres)": round(float(i.fuel_consumption), 2)})
                    elif i.alert_name == 'theft':
                        refuel_theft_data.append(
                            {"Date": date, "Time": str(alert_timestamp.hour) + ":" + str(alert_timestamp.minute),
                             "Activity": "Theft", "Fuel(in Litres)": round(float(i.fuel_consumption), 2)})

            # alert data for excel ends here
            # excel code starte here
            logger.debug("starting excel code")
            import pandas as pd
            from io import BytesIO
            logger.debug("bytes io importd")
            current_date = datetime.now()
            current_date = datetime.strftime(current_date, "%d-%B-%Y")
            df1 = pd.DataFrame(fuel_absolute_data)
            df2 = pd.DataFrame(dg_fuel_unit_data)
            df3 = pd.DataFrame(refuel_theft_data)
            logger.debug("dataframe done")
            logger.debug(fuel_absolute_data, "####")
            io = BytesIO()
            # excel_file_path = '/home/sqyuser/Desktop/Report DG Fuel & Unit Trend_{}.xlsx'.format(current_date)
            # writer = pd.ExcelWriter(excel_file_path, engine='xlsxwriter')
            writer = pd.ExcelWriter(io, engine='xlsxwriter')
            df1.to_excel(writer, sheet_name='Fuel Level', index=False)
            df2.to_excel(writer, sheet_name='DG Fuel & Unit Consumption', index=False)
            df3.to_excel(writer, sheet_name='DG Refuel & Theft Data', index=False)
            logger.debug("response###########################33: ", io.getvalue())
            writer.save()
            response = HttpResponse(io.getvalue(),
                                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename=Report DG Fuel & Unit Trend_{}.xlsx'.format(
                current_date)
            logger.debug("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@: ", response)
            return response
        except Exception as err:
            print(err)
            return Response({"status": 500, "msg": str(err)})'''



# class SubMeteringMonthlyTrendApi(APIView):
#     permission_classes = [AllowAny]

#     @entryExit
#     def post(self, request):
#         data = request.data
#         site_id = data.get("site_id", "")
#         user_type = data.get("user_type")
#         current_date = datetime.now().replace(day=15)
#         site = Site.objects.get(id=site_id)
#         current = datetime.now()
#         live_date = site.live_date.date()
#         liveDate = datetime.strftime(live_date, "%Y-%m-%d")
#         previous_date = current - timedelta(days=1)
#         print("previous_date", previous_date)
#         previousDate = datetime.strftime(previous_date, "%Y-%m-%d")
#         previous_month_year = live_date.strftime("%Y-%m")
#         print("previous_month_year", previous_month_year)
#         today_date = datetime.now()
#         current = today_date - timedelta(days=1)
#         month_list = []
#         final_data = []  # Initialize outside the site check
#         avg_data = []
#         if site:
#             aisle_group = AisleGroup.objects.filter(site_id=site_id)
#             for aisle in aisle_group:
#                 print("All legs", aisle)
#                 name = aisle.attached_leg_id
#                 aisleName = aisle.aisleGroupName
#                 energy_consumed_list = []
#                 avg_consumed_list = []
#                 for i in range(11, -1, -1):
#                     month = current_date - timedelta(days=int(i * 365 / 12))  # Cast the division result to int
#                     print("month%%%%", month)
#                     print("month##### : ", month.date())
#                     date_in_str = month.strftime("%b")
#                     year_in_str = month.strftime("%Y")
#                     modified_date = date_in_str + "-" + year_in_str
#                     month_list.append(modified_date)
#                     month_year = month.strftime("%Y-%m")
#                     print("month_year", month_year)
#                     daily = DailySiteReading.objects.filter(
#                         associated_Site=site,
#                         leg_id=name,
#                         reading_for__year=month.year,
#                         reading_for__gte=liveDate,
#                         reading_for__lte=previousDate,
#                         reading_for__month=month.month,
#                         is_visible=True,
#                     ).aggregate(Sum('unit_consumption'))
#                     print(daily)
#                     unit_consumed = daily['unit_consumption__sum']
#                     # avg_unit_consumed = daily["unit_consumption__avg"]
#                     if unit_consumed is None:
#                         unit_consumed = 0
#                     # if avg_unit_consumed is None:
#                     #     avg_unit_consumed = 0
#                     print(unit_consumed)
#                     energy_consumed_list.append(round(unit_consumed, 1))
#                     # avg_consumed_list.append(round(avg_unit_consumed, 1))
#                 final_data.append({"name": aisleName, "data": energy_consumed_list, "type": "column"})
#                 # avg_data.append({"name": aisleName, "data": avg_consumed_list, "type": "spline"})

#             # to calculate avg on site level
#             total_monthly_avg_data = 0
#             total_site_live_month = 0
#             monthly_avg_site_level_list = []
#             for i in range(11, -1, -1):
#                 month = current_date - timedelta(days=int(i * 365 / 12))  # Cast the division result to int
#                 print("month%%%%", month)
#                 print("month##### : ", month.date())
#                 date_in_str = month.strftime("%b")
#                 year_in_str = month.strftime("%Y")
#                 modified_date = date_in_str + "-" + year_in_str
#                 month_list.append(modified_date)
#                 month_year = month.strftime("%Y-%m")
#                 print("month_year", month_year)
#                 monthly = DailySiteReading.objects.filter(
#                     associated_Site=site,
#                     reading_for__year=month.year,
#                     reading_for__gte=liveDate,
#                     reading_for__lte=previousDate,
#                     reading_for__month=month.month,
#                     is_visible=True,
#                 ).aggregate(Sum('unit_consumption'))
#                 monthly_avg_site_level = monthly['unit_consumption__sum']
#                 print("month: {}".format(month), " data: ", monthly_avg_site_level)
#                 #total_monthly_avg_data += monthly_avg_site_level
#                 if month.month == live_date.month and month.year == live_date.year:   # live date month data
#                     try:
#                         monthly_avg = monthly_avg_site_level
#                         total_site_live_month += 1
                    
#                         total_monthly_avg_data += monthly_avg_site_level
#                     except Exception:
#                         monthly_avg=0
#                 elif monthly_avg_site_level is None:    # before live date month data
#                     monthly_avg = 0
#                 else:   #after live month data
#                     total_site_live_month += 1
                    
#                     total_monthly_avg_data += monthly_avg_site_level
#                     monthly_avg = total_monthly_avg_data / total_site_live_month
#                 monthly_avg_site_level_list.append(round(monthly_avg, 1))
#             final_data.append({"yAxis":1,"name": "ExpectedMonthlyUnits", "data": monthly_avg_site_level_list, "type": "spline"})

#         return Response(
#             {
#                 "result": 1,
#                 "months": month_list,
#                 "unit_consumed_data": final_data,
#                 "unit_consumed_avg_data": avg_data
#             }
#         )

class SubMeteringMonthlyTrendApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        # user_type = data.get("user_type") # Not used

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
             return Response({"result": 0, "msg": "Site not found"})
             
        # Date Setup
        today_date = datetime.now()
        current_date = today_date.replace(day=15)
        live_date = site.live_date.date()
        
        # Original logic used strictly 'previous_date' (yesterday) as end bound
        previous_date = today_date - timedelta(days=1)
        
        # Calculate the 12-month window
        generated_months = []
        month_list_str = []
        
        for i in range(11, -1, -1):
            m = current_date - timedelta(days=int(i * 365 / 12))
            generated_months.append(m)
            
            date_in_str = m.strftime("%b")
            year_in_str = m.strftime("%Y")
            modified_date = date_in_str + "-" + year_in_str
            month_list_str.append(modified_date)

        final_data = [] 
        avg_data = [] # Empty as per original

        if site:
            # 1. Fetch Per-Leg Data Grouped by Month (Optimized)
            # Filter efficiently by date range and site
            # We fetch a wider range to catch all possible data, then align in Python to match original logic
            
            leg_data_qs = DailySiteReading.objects.filter(
                associated_Site=site,
                is_visible=True,
                reading_for__gte=live_date, 
                reading_for__lte=previous_date
            ).annotate(
                month=TruncMonth('reading_for')
            ).values(
                'leg_id', 'month'
            ).annotate(
                total_consumption=Sum('unit_consumption')
            )

            # Dictionary for O(1) Lookup: (leg_id, year, month) -> sum
            leg_data_map = {}
            for entry in leg_data_qs:
                d = entry['month']
                if d:
                    key = (entry['leg_id'], d.year, d.month)
                    leg_data_map[key] = entry['total_consumption'] or 0

            # 2. Build Response for Each Aisle
            aisle_group = AisleGroup.objects.filter(site_id=site_id)
            
            for aisle in aisle_group:
                name_id = aisle.attached_leg_id
                aisle_name = aisle.aisleGroupName
                energy_consumed_list = []
                
                for m in generated_months:
                    # Logic: if month is outside [live_date, previous_date], it won't be in map 
                    # (due to query filter) or will be 0.
                    val = leg_data_map.get((name_id, m.year, m.month), 0)
                    energy_consumed_list.append(round(val, 1))

                final_data.append({"name": aisle_name, "data": energy_consumed_list, "type": "column"})

            # 3. Fetch Site Totals for ExpectedMonthlyUnits (Optimized)
            site_data_qs = DailySiteReading.objects.filter(
                associated_Site=site,
                is_visible=True,
                reading_for__gte=live_date,
                reading_for__lte=previous_date
            ).annotate(
                month=TruncMonth('reading_for')
            ).values(
                'month'
            ).annotate(
                total_consumption=Sum('unit_consumption')
            )
            
            site_data_map = {}
            for entry in site_data_qs:
                d = entry['month']
                if d:
                    site_data_map[(d.year, d.month)] = entry['total_consumption'] or 0

            # Calculate Running Average
            total_monthly_avg_data = 0
            total_site_live_month = 0
            monthly_avg_site_level_list = []

            for m in generated_months:
                monthly_avg_site_level = site_data_map.get((m.year, m.month))
                monthly_avg = 0
                
                # Logic matching original:
                # 1. Match Live Date Month (Reset/Start)
                if m.year == live_date.year and m.month == live_date.month:
                     val = monthly_avg_site_level or 0
                     monthly_avg = val
                     total_site_live_month += 1
                     total_monthly_avg_data += val
                
                # 2. Before Live Date (implicit check)
                elif monthly_avg_site_level is None and (m.year < live_date.year or (m.year == live_date.year and m.month < live_date.month)):
                     monthly_avg = 0
                
                # 3. After Live Date
                else: 
                     val = monthly_avg_site_level or 0
                     total_site_live_month += 1
                     total_monthly_avg_data += val
                     if total_site_live_month > 0:
                        monthly_avg = total_monthly_avg_data / total_site_live_month
                     else:
                        monthly_avg = 0

                monthly_avg_site_level_list.append(round(monthly_avg, 1))

            final_data.append({"yAxis":1, "name": "ExpectedMonthlyUnits", "data": monthly_avg_site_level_list, "type": "spline"})

        return Response(
            {
                "result": 1,
                "months": month_list_str,
                "unit_consumed_data": final_data,
                "unit_consumed_avg_data": avg_data
            }
        )


class SubmeteringSnapshotAPI(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        print("data : ", data)
        current_date = datetime.now()
        site_id = data.get('site_id')
        site = Site.objects.get(id=site_id)
        live_date = site.live_date
        print("live_ate : ", live_date)
        firstdate = current_date.replace(day=1)
        firstmnthDate = datetime.strftime(firstdate, "%Y-%m-%d")
        fromDate = datetime.strftime(live_date, "%Y-%m-%d")
        previous_date = current_date - timedelta(days=1)
        tillDate = datetime.strftime(previous_date, "%Y-%m-%d")
        print("dattata : ", type(tillDate))
        days = (current_date - live_date)
        print("days : ", days)
        totaldays = days.days + 1
        print("Totaldays :", totaldays)
        aisles = AisleGroup.objects.filter(site=site)
        all_leg_id = [aisle.attached_leg_id for aisle in aisles]
        daily = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                reading_for__gte=fromDate, reading_for__lte=tillDate)
        energyConsumed = 0.0
        avgData = 0.0
        if daily.exists():
            for i in daily:
                energyConsumed += i.unit_consumption
                avgData = round(energyConsumed / totaldays, 2)
        monthly = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_id,
                                                  reading_for__gte=firstmnthDate, reading_for__lte=tillDate).aggregate(
            Sum('unit_consumption'))
        unit_consumed = monthly['unit_consumption__sum']
        return Response({"status": 200, "alarms": 0, "energy_consumed": round(energyConsumed, 2), "dailyAvg": avgData,
                         "monthlyAvg": round(unit_consumed, 2), "firstmnthDate": firstmnthDate,
                         "current_date": tillDate, "live_date": fromDate})


class SubmeteringHourlyBarChart(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        #return Response({"status":201, "msg":"testing","data":data})
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        print("function start time is : ", start_time)
        site = Site.objects.get(id=site_id)
        # return Response({"status":200, "msg":"working fine"})
        date = data.get("date", '')
        date = datetime.strptime(date, "%Y/%m/%d")
        print("date ::", date)
        print("ii", date.date())
        hourList = []
        dataList = []
        all_leg_id = DailySiteReading.objects.filter(associated_Site=site, reading_for=date.date()).distinct("leg_id")
        oneDayData = HourlySiteReading.objects.filter(associated_Site=site_id, reading_from__date=date.date(),
                                                      is_visible=True)
        print("@@@@@@@@@@@@@@")
        for leg in all_leg_id:
            aisle_name = AisleGroup.objects.filter(site=site_id, attached_leg_id=leg.leg_id)
            if aisle_name.exists():
                name = aisle_name[0].aisleGroupName
            else:
                name = leg.leg_id
            print('leg :', leg)
            unitConsumptionList = []
            savingConsumptionList = []
            hourList = []
            for i in range(24):
                current_hour = i
                print("current_hour", current_hour)
                if current_hour <= 9:
                    hr = '0' + str(current_hour) + ':00'
                else:
                    hr = str(current_hour) + ':00'
                hourList.append(hr)
                unit_consumption = 0.0
                energy_saved = 0.0
                if aisle_name.exists():
                    hourly = oneDayData.filter(aisle_group=aisle_name[0], reading_from__hour=current_hour)
                else:
                    hourly = oneDayData.filter(leg_id=leg, reading_from__hour=current_hour)
                print('hourly data', hourly)
                if hourly.exists():
                    for j in hourly:
                        try:
                            unit_consumption += j.unit_consumption
                        except Exception as e:
                            print("exception", e)
                unitConsumptionList.append(round(unit_consumption, 2))
            print("unit data: ", unitConsumptionList)
            dataList.append({"name": name, "data": unitConsumptionList, "type": 'column'})
        end_time = datetime.now()
        print("function end time is : ", end_time)
        time_taken = end_time - start_time
        print("time_taken", time_taken)
        hourList = ["00:00", "01:00", "02:00", "03:00", "04:00", "05:00", "06:00", "07:00", "08:00", "09:00", "10:00",
                    "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00",
                    "22:00", "23:00"]
        return Response({"result": 1, "Hours": hourList, "Data": dataList})


class SubmeteringHourlyBarChartNew(APIView):

    @entryExit
    def post(self, request):
        start_time = datetime.now()
        from collections import defaultdict
        from django.db.models.functions import ExtractHour
        data = request.data
        site_id = data.get("site_id")
        date = datetime.strptime(data.get("date"), "%Y/%m/%d").date()
        print("######################", datetime.now())
        site = Site.objects.get(id=site_id)
        print("site: ", site)
        # Fixed hour list
        hour_list = [f"{str(i).zfill(2)}:00" for i in range(24)]
        # print("hour_list: ", hour_list)
        # -------------------------
        # Fetch leg IDs
        # -------------------------
        legs = (
            DailySiteReading.objects
            .filter(associated_Site=site, reading_for=date)
            .values_list("leg_id", flat=True)
            .distinct()
        )
        # print("legs: ", legs)

        # -------------------------
        # Fetch aisle mappings
        # -------------------------
        aisle_map = {
            ag.attached_leg_id: ag
            for ag in AisleGroup.objects.filter(site=site_id, attached_leg_id__in=legs)
        }
        print("aisle group: ", datetime.now())

        # -------------------------
        # Fetch & aggregate hourly data in ONE QUERY
        # -------------------------
        hourly_data = (
            HourlySiteReading.objects
            .filter(
                associated_Site=site_id,
                reading_from__date=date,
                is_visible=True
            )
            .annotate(hour=ExtractHour("reading_from"))
            .values("leg_id", "aisle_group", "hour")
            .annotate(total=Sum("unit_consumption"))
        )
        print("hourly data: ", datetime.now())

        # -------------------------
        # Build lookup dict
        # -------------------------
        data_lookup = defaultdict(lambda: defaultdict(float))

        for row in hourly_data:
            key = row["aisle_group"] or row["leg_id"]
            data_lookup[key][row["hour"]] += row["total"] or 0.0

        # -------------------------
        # Build response data
        # -------------------------
        data_list = []

        for leg_id in legs:
            aisle = aisle_map.get(leg_id)
            key = aisle.id if aisle else leg_id
            name = aisle.aisleGroupName if aisle else leg_id

            hourly_values = [
                round(data_lookup[key].get(hour, 0.0), 2)
                for hour in range(24)
            ]

            data_list.append({
                "name": name,
                "data": hourly_values,
                "type": "column"
            })

        end_time = datetime.now()
        print("Time taken:", end_time - start_time)

        return Response({
            "result": 1,
            "Hours": hour_list,
            "Data": data_list
        })

# class SubmeteringHourlyBarChartNew(APIView):

#     @entryExit
#     def post(self, request):
#         start_time = datetime.now()
#         from collections import defaultdict
#         from django.db.models.functions import ExtractHour
#         data = request.data
#         site_id = data.get("site_id")
#         date = datetime.strptime(data.get("date"), "%Y/%m/%d").date()
#         print("######################", datetime.now())
#         site = Site.objects.get(id=site_id)
#         print("site: ", site)
#         # Fixed hour list
#         hour_list = [f"{str(i).zfill(2)}:00" for i in range(24)]
#         # print("hour_list: ", hour_list)
#         # -------------------------
#         # Fetch leg IDs
#         # -------------------------
#         legs = (
#             HourlySiteReading.objects
#             .filter(associated_Site=site, reading_from__date=date, is_visible=True)
#             .values_list("leg_id", flat=True)
#             .distinct()
#         )
#         # print("legs: ", legs)

#         # -------------------------
#         # Fetch aisle mappings
#         # -------------------------
#         aisle_map = {
#             ag.attached_leg_id: ag
#             for ag in AisleGroup.objects.filter(site=site_id, attached_leg_id__in=legs)
#         }
#         print("aisle group: ", datetime.now())

#         # -------------------------
#         # Fetch & aggregate hourly data in ONE QUERY
#         # -------------------------
#         hourly_data = (
#             HourlySiteReading.objects
#             .filter(
#                 associated_Site=site_id,
#                 reading_from__date=date,
#                 is_visible=True
#             )
#             .annotate(hour=ExtractHour("reading_from"))
#             .values("leg_id", "aisle_group", "hour")
#             .annotate(total=Sum("unit_consumption"))
#         )
#         print("hourly data: ", datetime.now())

#         # -------------------------
#         # Build lookup dict
#         # -------------------------
#         data_lookup = defaultdict(lambda: defaultdict(float))

#         for row in hourly_data:
#             key = row["aisle_group"] or row["leg_id"]
#             data_lookup[key][row["hour"]] += row["total"] or 0.0

#         # -------------------------
#         # Build response data
#         # -------------------------
#         data_list = []

#         for leg_id in legs:
#             aisle = aisle_map.get(leg_id)
#             key = aisle.id if aisle else leg_id
#             name = aisle.aisleGroupName if aisle else leg_id

#             hourly_values = [
#                 round(data_lookup[key].get(hour, 0.0), 2)
#                 for hour in range(24)
#             ]

#             data_list.append({
#                 "name": name,
#                 "data": hourly_values,
#                 "type": "column"
#             })

#         end_time = datetime.now()
#         print("Time taken:", end_time - start_time)

#         return Response({
#             "result": 1,
#             "Hours": hour_list,
#             "Data": data_list
#         })



def DGfuelMonthlyTrendMultipleAisles(site_id):
    try:
            #data = request.data
            #site_id = data.get("site_id")
            aisle_groups = AisleGroup.objects.filter(site=int(site_id))

            # Separate mains and DG aisles into separate lists
            mains_aisles = []
            dg_aisles = []

            for aisle in aisle_groups:
                if aisle.power_source == 0:  # Mains
                    mains_aisles.append(aisle.attached_leg_id)
                elif aisle.power_source == 1:  # DG
                    dg_aisles.append(aisle.attached_leg_id)

            if not mains_aisles and not dg_aisles:
                return Response({"status": 400, "msg": "No matching aisles found for the site."})

            # Prepare lists to store data for each month
            current_date = datetime.now().replace(day=15)
            dg_fuel_consumption_list = []
            mains_unit_consumption_list = []
            dg_unit_consumption_list = []
            month_list = []

            # Iterate over the last 12 months
            for i in range(11, -1, -1):
                month = current_date - timedelta(days=int(i * 365 / 12))
                date_in_str = month.strftime("%b")
                year_in_str = month.strftime("%Y")
                modified_date = f"{date_in_str}-{year_in_str}"
                month_list.append(modified_date)

                # Fuel data for the month
                fuel_data = DgFuelConsumptionData.objects.filter(
                    site=site_id,
                    created__year=month.year,
                    created__month=month.month
                ).order_by('created')

                dg_fuel_alert_data = DGFuelAlertsData.objects.filter(
                    site=site_id,
                    created__year=month.year,
                    created__month=month.month,
                    alert_name='refuel'
                ).aggregate(Sum('fuel_consumption'))

                # Calculate DG fuel consumption
                refuel_value = dg_fuel_alert_data['fuel_consumption__sum'] or 0
                initial_fuel_value = 0
                last_fuel_value = 0
                if fuel_data.exists():
                    first_entry = fuel_data[0]
                    initial_fuel_value = first_entry.fuel_consumption
                    last_entry = fuel_data.last()
                    last_fuel_value = last_entry.fuel_consumption

                total_dg_fuel_consumed = initial_fuel_value + refuel_value - last_fuel_value
                total_dg_fuel_consumed = max(total_dg_fuel_consumed, 0)
                dg_fuel_consumption_list.append(round(total_dg_fuel_consumed, 2))

                # Calculate mains unit consumption
                total_mains_unit_consumed = DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group__in=mains_aisles,
                    reading_for__year=month.year,
                    reading_for__month=month.month
                ).aggregate(Sum('unit_consumption'))['unit_consumption__sum'] or 0

                # Calculate DG unit consumption
                total_dg_unit_consumed = DailySiteReading.objects.filter(
                    associated_Site=site_id,
                    aisle_group__in=dg_aisles,
                    reading_for__year=month.year,
                    reading_for__month=month.month
                ).aggregate(Sum('unit_consumption'))['unit_consumption__sum'] or 0

                # Append values to their respective lists
                mains_unit_consumption_list.append(round(total_mains_unit_consumed, 2))
                dg_unit_consumption_list.append(round(total_dg_unit_consumed, 2))

            return Response({
                "status": 200,
                "test_arg" : "Hello World",
                "months": month_list,
                "dg_fuel_monthly": dg_fuel_consumption_list,
                "mains_unit_consumption_monthly": mains_unit_consumption_list,
                "dg_unit_consumption_monthly": dg_unit_consumption_list
            })
    except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class DgFuelMonthlyTrend(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")
            if site_id == int(124):
                print("inside 124 condition") 
                return DGfuelMonthlyTrendMultipleAisles(124)
            aisle_group = AisleGroup.objects.filter(site=site_id)
            mains_aisle = 0
            dg_aisle = 0
            for aisle in aisle_group:
                if aisle.power_source == 0:
                    mains_aisle = aisle.attached_leg_id
                elif aisle.power_source == 1:
                    dg_aisle = aisle.attached_leg_id
            if not mains_aisle and not dg_aisle:
                return Response({"status": 400, "msg": "aisle not matched"})
            current_date = datetime.now().replace(day=15)
            dg_fuel_consumption_list = []
            mains_unit_consumption_list = []
            dg_unit_consumption_list = []
            month_list = []
            for i in range(11, -1, -1):
                month = current_date - timedelta(days=int(i * 365 / 12))
                print("month##### : ", month.date())
                date_in_str = month.strftime("%b")
                year_in_str = month.strftime("%Y")
                modified_date = date_in_str + "-" + year_in_str
                month_list.append(modified_date)
                start_date = datetime.now().date().replace(year=datetime.now().year - 1, month=datetime.now().month % 12 + 1,day=1)
                fuel = list(
                        DgUnitConsumption.objects
                        .filter(
                            site_id=site_id,
                            created__range=(start_date, datetime.now().date())
                        )
                        .annotate(month=TruncMonth('created'))
                        .values('month')
                        .annotate(total_units=Sum('dg_fuel_consumption'))
                        .order_by('month')
                        .values_list('total_units', flat=True)
                    )
                fuel_data = DgFuelConsumptionData.objects.filter(site=site_id, created__year=month.year, created__month=month.month).order_by('created')
                dg_fuel_alert_data = DGFuelAlertsData.objects.filter(site=site_id, created__year=month.year, created__month=month.month, alert_name='refuel').aggregate(Sum('fuel_consumption'))
                refuel_value = 0
                dg_fuel_alert_data = dg_fuel_alert_data['fuel_consumption__sum']
                if dg_fuel_alert_data is not None:
                    refuel_value = dg_fuel_alert_data
                initial_fuel_value = 0
                last_fuel_value = 0
                if fuel_data.exists():
                    first_entry = fuel_data[0]
                    initial_fuel_value = first_entry.fuel_consumption
                    last_entry = fuel_data.last()
                    last_fuel_value = last_entry.fuel_consumption
                total_dg_fuel_consumed = initial_fuel_value + refuel_value - last_fuel_value
                if total_dg_fuel_consumed < 0:
                    total_dg_fuel_consumed = 0
                dg_fuel_consumption_list.append(round(total_dg_fuel_consumed, 2))
                mains_unit_consumed = DailySiteReading.objects.filter(associated_Site=site_id, aisle_group=mains_aisle, reading_for__year=month.year, reading_for__month=month.month).aggregate(Sum('unit_consumption'))
                dg_unit_consumed = DailySiteReading.objects.filter(associated_Site=site_id, aisle_group=dg_aisle,
                                                                      reading_for__year=month.year,
                                                                      reading_for__month=month.month).aggregate(
                    Sum('unit_consumption'))
                mains_unit_consumed = mains_unit_consumed['unit_consumption__sum']
                dg_unit_consumed = dg_unit_consumed['unit_consumption__sum']
                if mains_unit_consumed is not None:
                    mains_unit = mains_unit_consumed
                else:
                    mains_unit = 0
                if dg_unit_consumed is not None:
                    dg_unit = dg_unit_consumed
                else:
                    dg_unit = 0
                mains_unit_consumption_list.append(round(mains_unit, 2))
                dg_unit_consumption_list.append(round(dg_unit, 2))
            return Response({"status": 200, "test_Args" : ["Not the 124"] ,"months": month_list, "dg_fuel_monthly": fuel,
                             "mains_unit_consumption_monthly": mains_unit_consumption_list,
                             "dg_unit_consumption_monthly": dg_unit_consumption_list})
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class NewSubMeteringMonthlyTrendApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        import calendar
        data = request.data
        site_id = data.get("site_id", "")
        user_type = data.get("user_type")
        current_date = datetime.now().replace(day=15)
        site = Site.objects.get(id=site_id)
        current = datetime.now()
        live_date = site.live_date.date()
        liveDate = datetime.strftime(live_date, "%Y-%m-%d")
        previous_date = current - timedelta(days=1)
        print("previous_date", previous_date)
        previousDate = datetime.strftime(previous_date, "%Y-%m-%d")
        previous_month_year = live_date.strftime("%Y-%m")
        print("previous_month_year", previous_month_year)
        today_date = datetime.now()
        current = today_date - timedelta(days=1)
        month_list = []
        final_data = []  # Initialize outside the site check
        avg_data = []
        if site:
            aisle_group = AisleGroup.objects.filter(site_id=site_id)
            for aisle in aisle_group:
                print("All legs", aisle)
                name = aisle.attached_leg_id
                aisleName = aisle.aisleGroupName
                energy_consumed_list = []
                avg_consumed_list = []
                for i in range(11, -1, -1):
                    month = current_date - timedelta(days=int(i * 365 / 12))  # Cast the division result to int
                    print("month%%%%", month)
                    print("month##### : ", month.date())
                    date_in_str = month.strftime("%b")
                    year_in_str = month.strftime("%Y")
                    modified_date = date_in_str + "-" + year_in_str
                    month_list.append(modified_date)
                    month_year = month.strftime("%Y-%m")
                    print("month_year", month_year)
                    daily = DailySiteReading.objects.filter(
                        associated_Site=site,
                        leg_id=name,
                        reading_for__year=month.year,
                        reading_for__gte=liveDate,
                        reading_for__lte=previousDate,
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum('unit_consumption'))
                    print(daily)
                    unit_consumed = daily['unit_consumption__sum']
                    # avg_unit_consumed = daily["unit_consumption__avg"]
                    if unit_consumed is None:
                        unit_consumed = 0
                    # if avg_unit_consumed is None:
                    #     avg_unit_consumed = 0
                    print(unit_consumed)
                    energy_consumed_list.append(round(unit_consumed, 1))
                    # avg_consumed_list.append(round(avg_unit_consumed, 1))
                final_data.append({"name": aisleName, "data": energy_consumed_list, "type": "column"})
                # avg_data.append({"name": aisleName, "data": avg_consumed_list, "type": "spline"})

            # to calculate avg on site level
            total_monthly_avg_data = 0
            total_site_live_month = 0
            monthly_avg_site_level_list = []
            for i in range(11, -1, -1):
                month = current_date - timedelta(days=int(i * 365 / 12))  # Cast the division result to int
                print("month%%%%", month)
                print("month##### : ", month.date())
                date_in_str = month.strftime("%b")
                year_in_str = month.strftime("%Y")
                modified_date = date_in_str + "-" + year_in_str
                month_list.append(modified_date)
                month_year = month.strftime("%Y-%m")
                print("month_year", month_year)
                if month.month == live_date.month and month.year == live_date.year:
                    monthly = DailySiteReading.objects.filter(
                        associated_Site=site,
                        reading_for__year=month.year,
                        reading_for__gte=liveDate,
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum('unit_consumption'))
                    monthly_avg_site_level = monthly['unit_consumption__sum']
                    print("month: {}".format(month), " data: ", monthly_avg_site_level)
                elif month.month == today_date.month and month.year == today_date.year:
                    monthly = DailySiteReading.objects.filter(
                        associated_Site=site,
                        reading_for__year=month.year,
                        reading_for__lt=today_date.date(),
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum('unit_consumption'))
                    monthly_avg_site_level = monthly['unit_consumption__sum']
                    print("month: {}".format(month), " data: ", monthly_avg_site_level)
                else:
                    monthly = DailySiteReading.objects.filter(
                        associated_Site=site,
                        reading_for__year=month.year,
                        reading_for__month=month.month,
                        is_visible=True,
                    ).aggregate(Sum('unit_consumption'))
                    monthly_avg_site_level = monthly['unit_consumption__sum']
                    print("month: {}".format(month), " data: ", monthly_avg_site_level)
                # total_monthly_avg_data += monthly_avg_site_level
                if month.month == live_date.month and month.year == live_date.year:  # live date month data
                    try:
                        

                        total_days_in_month = calendar.monthrange(month.year, month.month)[1]
                        diff_from_live_date = total_days_in_month - live_date.day + 1
                        monthly_avg_site_level = (monthly_avg_site_level/diff_from_live_date) * total_days_in_month
                        monthly_avg = monthly_avg_site_level

                        # total_site_live_month += 1
                        # total_monthly_avg_data += monthly_avg_site_level
                    except Exception:
                        monthly_avg = 0
                elif monthly_avg_site_level is None:  # before live date month data
                    monthly_avg = 0
                else:  # after live month data
                    # total_site_live_month += 1

                    # total_monthly_avg_data += monthly_avg_site_level
                    # monthly_avg = total_monthly_avg_data / total_site_live_month
                    if month.month == today_date.month and month.year == today_date.year:
                        total_days_in_month = calendar.monthrange(month.year, month.month)[1]
                        total_days = today_date.day - 1
                        monthly_avg = (monthly_avg_site_level/total_days) * total_days_in_month
                        #avg_data.append({"tm":total_days_in_month, "td": total_days, "avg":monthly_avg, "month": month.day, "tdate":today_date})
                    else:
                        monthly_avg = monthly_avg_site_level
                monthly_avg_site_level_list.append(round(monthly_avg, 1))
            final_data.append(
                {"yAxis": 1, "name": "ExpectedMonthlyUnits", "data": monthly_avg_site_level_list, "type": "spline"})

        return Response(
            {
                "result": 1,
                "months": month_list,
                "unit_consumed_data": final_data,
                "unit_consumed_avg_data": avg_data
            }
        )

'''class AlarmsList(APIView):
    def post(self,request):
        data=request.data
        site_id=data.get('siteId')
        data=[]
        site=Site.objects.get(id=site_id)
        alarms=NewAlarmsNotifications.objects.filter(site_id=site).distinct('alarm_type')
        #count=alarms.count()
        for i in alarms:
            data.append({"name":i.get_alarm_type_display()})
        return Response({"status":200,"data":data})'''

class AlarmsList(APIView):
    def post(self, request):
        data = request.data
        site = int(data.get('siteId'))
        data = []
        #site = Site.objects.get(id=site_id)
        total_alarms=NewAlarmsNotifications.objects.filter(site_id=site).count()
        high_priority = NewAlarmsNotifications.objects.filter(site_id=site,alarm_priority=0).count()
        medium_priority = NewAlarmsNotifications.objects.filter(site_id=site,alarm_priority=1).count()
        active_alarms = NewAlarmsNotifications.objects.filter(site_id=site,is_active=True).count()
        alarms = NewAlarmsNotifications.objects.filter(site_id=site).distinct('alarm_type')
        for i in alarms:
            count= NewAlarmsNotifications.objects.filter(site_id=site, alarm_type= i.alarm_type).count()
            data.append({"name": i.get_alarm_type_display(),"count":count,"priority":i.get_alarm_priority_display(), "alarm_type": i.alarm_type})
        return Response({"status": 200,"total_alarm":total_alarms,"high_priority":high_priority,"medium_priority":medium_priority,"active_alarms":active_alarms, "data": data})


class AlarmsListDetail(APIView):
    def post(self, request):
        data =request.data
        try:
            site_id = data.get('siteId')
            alarm_type = data.get('alarm_type')
            alarms = NewAlarmsNotifications.objects.filter(site_id=site_id, alarm_type=int(alarm_type))
            serializer = AlarmListSerializer(alarms, many=True)
            return Response({"status": 200, "data": serializer.data})
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


"""class EnergySavingMonthlyBarChartOptimized(APIView):
    permission_classes = [AllowAny]
    @entryExit
    def post(self, request):
        t1 = time.time()
        data = request.data
        site_id = data.get("site_id", '')
        if int(site_id) == 34:
            site_id = 29
        site = Site.objects.get(id=site_id)
        live_date = site.live_date
        previous_date = live_date - timedelta(days=1)
        from_date = data.get("from_date", '')
        till_date = data.get("till_date", '')
        user_type = int(data.get("user_type", ''))
        fromDate = datetime.strptime(from_date, "%Y/%m/%d")
        tillDate = datetime.strptime(till_date, "%Y/%m/%d")
        currentDate = datetime.now()
        dateList = []
        dataList = []
        savingDataList = []
        if tillDate.month == currentDate.month:
            print("$$$$$$$$$$$$$$$$$$$")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
            all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
            all_data = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_ids,
                                                       reading_for__range=[fromDate.date(), tillDate.date()],
                                                       is_visible=True)
            print("all_data",all_data)
            all_dates = [(tillDate - timedelta(days=29 - i)).date() for i in range(30)]
            print("all dates: ", all_dates)
            output = {}
            for i in all_data:
                # print("all_data : ",all_data)
                print("##: ", i.reading_for)
                indx = all_dates.index(i.reading_for)
                aisle_name = i.aisle_group.aisleGroupName
                if aisle_name in output:
                    output[aisle_name][indx] = i.unit_consumption
                else:
                    output[aisle_name] = [0 for i in range(31)]
                    if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                        output[aisle_name][indx] = i.unit_consumption

            for i, j in output.items():
                dataList.append({"name": i, "data": j, "type": "column"})
                savingDataList.append({"name": i, "data": j, "type": "column"})
            if site.is_live:
                if int(data.get("site_id", '')) == 34:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276])
                else:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                baselineList = []
                if baseline.exists():
                    if int(data.get("site_id", '')) == 34:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                            aisle_group__in=[259, 260, 261,
                                                                                             276])
                    elif int(data.get("site_id", '')) == 29:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                            Q(aisle_group__in=[259, 260, 261, 276]))
                    else:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                    # latest_baseline_value = latest_baseline_value['baseline_value__sum']
                    for i in range(30):
                        date = tillDate - timedelta(days=29 - i)
                        baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                            Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                            Sum('baseline_value'))
                        try:
                            baseline_value = baseline_value['baseline_value__sum']
                            if baseline_value is not None:
                                baselineList.append(round(baseline_value, 2))
                            else:
                                baselineList.append(0)
                        except Exception as e:
                            print('Exception 1 is', e)
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
        else:
            print("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^")
            total_days = (tillDate.day - fromDate.day) + 1
            print("total_days",total_days)
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276])
                else:
                    aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
            all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
            all_data = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_ids,
                                                       reading_for__range=[fromDate.date(), tillDate.date()],
                                                       is_visible=True)
            all_dates = [(tillDate - timedelta(days=(total_days - 1) - i)).date() for i in range(total_days)]
            print("dates: ", all_dates)
            output = {}
            for i in all_data:
                print("@@: ", i.reading_for)
                indx = all_dates.index(i.reading_for)
                aisle_name = i.aisle_group.aisleGroupName
                if aisle_name in output:
                    output[aisle_name][indx] = i.unit_consumption
                else:
                    output[aisle_name] = [0 for i in range(31)]
                    if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                        output[aisle_name][indx] = i.unit_consumption

            for i, j in output.items():
                dataList.append({"name": i, "data": j, "type": "column"})
                savingDataList.append({"name": i, "data": j, "type": "column"})
            if site.is_live:
                if int(data.get("site_id", '')) == 34:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276])
                else:
                    baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                baselineList = []
                if baseline.exists():
                    if int(data.get("site_id", '')) == 34:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                            aisle_group__in=[259, 260, 261,
                                                                                             276])
                    elif int(data.get("site_id", '')) == 29:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                            Q(aisle_group__in=[259, 260, 261, 276]))
                    else:
                        latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                    for i in range(total_days):
                        date = tillDate - timedelta(days=(total_days - 1) - i)
                        baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                            Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                            Sum('baseline_value'))
                        try:
                            baseline_value = baseline_value['baseline_value__sum']
                            if baseline_value is not None:
                                baselineList.append(round(baseline_value, 2))
                            else:
                                baselineList.append(0)
                        except Exception as e:
                            baseline_value = 0.0
                            baselineList.append(baseline_value)
                            print('Exception 2 is', e)
                dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
        t2 = time.time()
        return Response({"result": 1, "Dates": dateList, "Data": dataList, "SavingData": savingDataList})"""
    
class EnergySavingMonthlyBarChartbackup(APIView):
    permission_classes = [AllowAny]
    @entryExit
    def post(self, request):
        t1 = time.time()
        data = request.data
        site_id = data.get("site_id", '')
        if int(site_id) == 34:
            site_id = 29
        try:
            site = Site.objects.get(id=site_id)
            live_date = site.live_date
            previous_date = live_date - timedelta(days=1)
            from_date = data.get("from_date", '')
            till_date = data.get("till_date", '')
            user_type = int(data.get("user_type", ''))
            fromDate = datetime.strptime(from_date, "%Y/%m/%d")
            tillDate = datetime.strptime(till_date, "%Y/%m/%d")
            currentDate = datetime.now()
            dateList = []
            dataList = []
            savingDataList = []
            a=''
            if tillDate.month == currentDate.month:
                print("$$$$$$$$$$$$$$$$$$$")
                a="tttt"
                if user_type == 1:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_ids,
                                                           reading_for__range=[tillDate.date()-timedelta(days=29), tillDate.date()],
                                                           is_visible=True)
                print("all_data",all_data)
                all_dates = [(tillDate - timedelta(days=29 - i)).date() for i in range(30)]
                print("all dates: ", all_dates)
                output = {}
                for i in all_data:
                    # print("all_data : ",all_data)
                    print("##: ", i.reading_for)
                    indx = all_dates.index(i.reading_for)
                    aisle_name = i.aisle_group.aisleGroupName
                    if aisle_name in output:
                        if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption,2)
                    else:
                        output[aisle_name] = [0 for i in range(30)]
                        if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption,2)
        
                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", '')) == 34:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276])
                    else:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", '')) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                                aisle_group__in=[259, 260, 261,
                                                                                                 276])
                        elif int(data.get("site_id", '')) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                                Q(aisle_group__in=[259, 260, 261, 276]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                        # latest_baseline_value = latest_baseline_value['baseline_value__sum']
                        for i in range(30):
                            date = tillDate - timedelta(days=29 - i)
                            baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                                Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                                Sum('baseline_value'))
                            try:
                                baseline_value = baseline_value['baseline_value__sum']
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                print('Exception 1 is', e)
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                    dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
            else:
                print("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^")
                a='1111'
                total_days = (tillDate - fromDate).days + 1
                print("total_days",total_days)
                if user_type == 1:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_ids,
                                                           reading_for__range=[fromDate.date(), tillDate.date()],
                                                           is_visible=True)
                all_dates = [(tillDate - timedelta(days=(total_days-1) - i)).date() for i in range(total_days)]
                print("dates: ", all_dates)
                output = {}
                for i in all_data:
                    print("@@: ", i.reading_for)
                    indx = all_dates.index(i.reading_for)
                    aisle_name = i.aisle_group.aisleGroupName
                    if aisle_name in output:
                        if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption,2)
                    else:
                        output[aisle_name] = [0 for i in range(total_days)]
                        if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                            output[aisle_name][indx] = round(i.unit_consumption,2)
        
                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", '')) == 34:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276])
                    else:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", '')) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                                aisle_group__in=[259, 260, 261,
                                                                                                 276])
                        elif int(data.get("site_id", '')) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                                Q(aisle_group__in=[259, 260, 261, 276]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                        for i in range(total_days):
                            date = tillDate - timedelta(days=(total_days - 1) - i)
                            baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                                Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                                Sum('baseline_value'))
                            try:
                                baseline_value = baseline_value['baseline_value__sum']
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                                print('Exception 2 is', e)
                    dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
            t2 = time.time()
            return Response({"result": 1, "Dates": all_dates, "Data": dataList, "SavingData": savingDataList})
        except Exception as err:
            return Response({"status": 500, "msg": str(err), "dates": all_dates, "a":a})


# new api by abhishek (28-02-2024)
class EnergySavingMonthlyBarChart(APIView):
    permission_classes = [AllowAny]
    @entryExit
    def post(self, request):
        t1 = time.time()
        data = request.data
        site_id = data.get("site_id", '')
        if int(site_id) == 34:
            site_id = 29
        try:
            site = Site.objects.get(id=site_id)
            live_date = site.live_date
            previous_date = live_date - timedelta(days=1)
            from_date = data.get("from_date", '')
            till_date = data.get("till_date", '')
            user_type = int(data.get("user_type", ''))
            fromDate = datetime.strptime(from_date, "%Y/%m/%d")
            tillDate = datetime.strptime(till_date, "%Y/%m/%d")
            currentDate = datetime.now()
            dateList = []
            dataList = []
            savingDataList = []
            a=''
            if tillDate.month == currentDate.month:
                print("$$$$$$$$$$$$$$$$$$$")
                a="tttt"
                if user_type == 1:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_ids,
                                                           reading_for__range=[tillDate.date()-timedelta(days=29), tillDate.date()],
                                                           is_visible=True)
                print("all_data",all_data)
                all_dates = [(tillDate - timedelta(days=29 - i)).date() for i in range(30)]
                print("all dates: ", all_dates)
                output = {}
                for i in all_data:
                    aisle_name = i.aisle_group.aisleGroupName
                    if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                        indx = all_dates.index(i.reading_for) if i.reading_for in all_dates else None
                        if aisle_name in output:
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)
                        else:
                            output[aisle_name] = [0 for _ in range(30)]
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)


                        
                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", '')) == 34:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276, 710])
                    else:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", '')) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                                aisle_group__in=[259, 260, 261,
                                                                                                 276, 710])
                        elif int(data.get("site_id", '')) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                                Q(aisle_group__in=[259, 260, 261, 276, 710]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                        # latest_baseline_value = latest_baseline_value['baseline_value__sum']
                        for i in range(30):
                            date = tillDate - timedelta(days=29 - i)
                            baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                                Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                                Sum('baseline_value'))
                            try:
                                baseline_value = baseline_value['baseline_value__sum']
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                print('Exception 1 is', e)
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                    dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
            else:
                print("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^")
                a='1111'
                total_days = (tillDate - fromDate).days + 1
                print("total_days",total_days)
                if user_type == 1:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id)
                else:
                    if int(data.get("site_id", '')) == 34:
                        aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                    else:
                        aisle_group = AisleGroup.objects.filter(site_id=site_id, is_visible=True)
                all_leg_ids = [leg.attached_leg_id for leg in aisle_group]
                all_data = DailySiteReading.objects.filter(associated_Site=site, leg_id__in=all_leg_ids,
                                                           reading_for__range=[fromDate.date(), tillDate.date()],
                                                           is_visible=True)
                all_dates = [(tillDate - timedelta(days=(total_days-1) - i)).date() for i in range(total_days)]
                print("dates: ", all_dates)
                output = {}
                for i in all_data:
                    aisle_name = i.aisle_group.aisleGroupName
                    if (user_type in [4, 5] and previous_date.date() < i.reading_for) or user_type == 1:
                        indx = all_dates.index(i.reading_for) if i.reading_for in all_dates else None
                        if aisle_name in output:
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)
                        else:
                            output[aisle_name] = [0 for _ in range(30)]
                            if indx is not None:
                                output[aisle_name][indx] = round(i.unit_consumption, 2)

        
                for i, j in output.items():
                    dataList.append({"name": i, "data": j, "type": "column"})
                    savingDataList.append({"name": i, "data": j, "type": "column"})
                if site.is_live:
                    if int(data.get("site_id", '')) == 34:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id, leg_id__in=[259, 260, 261, 276, 710])
                    else:
                        baseline = SiteBaseline.objects.filter(associated_site_id=site_id)
                    baselineList = []
                    if baseline.exists():
                        if int(data.get("site_id", '')) == 34:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site,
                                                                                aisle_group__in=[259, 260, 261,
                                                                                                 276, 710])
                        elif int(data.get("site_id", '')) == 29:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=29).exclude(
                                Q(aisle_group__in=[259, 260, 261, 276, 710]))
                        else:
                            latest_baseline_value = SiteBaseline.objects.filter(associated_site_id=site)
                        for i in range(total_days):
                            date = tillDate - timedelta(days=(total_days - 1) - i)
                            baseline_value = latest_baseline_value.filter(Q(baseline_to__gte=date.date()) | Q(
                                Q(baseline_from__lte=date.date()) & Q(baseline_to__isnull=True))).aggregate(
                                Sum('baseline_value'))
                            try:
                                baseline_value = baseline_value['baseline_value__sum']
                                if baseline_value is not None:
                                    baselineList.append(round(baseline_value, 2))
                                else:
                                    baselineList.append(0)
                            except Exception as e:
                                baseline_value = 0.0
                                baselineList.append(baseline_value)
                                print('Exception 2 is', e)
                    dataList.append({"name": "baseline", "data": baselineList, 'type': 'spline'})
            t2 = time.time()
            return Response({"result": 1, "Dates": all_dates, "Data": dataList, "SavingData": savingDataList})
        except Exception as err:
            return Response({"status": 500, "msg": str(err), "dates": all_dates, "a":a})





class EnergySavingMonthlyBarChart_new(APIView):
    permission_classes = [AllowAny]
    @entryExit
    def post(self, request):
        data = request.data
        site_id = int(data.get("site_id", 0))
        if site_id == 34:
            site_id = 29

        try:
            site = Site.objects.get(id=site_id)
            from_date = datetime.strptime(data.get("from_date", ""), "%Y/%m/%d")
            till_date = datetime.strptime(data.get("till_date", ""), "%Y/%m/%d")
            user_type = int(data.get("user_type", 0))
            #if(from_date > site.live_date):
             #   from_date = site.live_date
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

            # Add is_visible condition only if user_type is NOT 1
            if user_type != 1 and int(data.get("site_id", 0)) != 34:
                filter_condition &= ~Q(is_visible=False)

            aisle_group = AisleGroup.objects.filter(filter_condition)
            aisle_map = {aisle.attached_leg_id: aisle.aisleGroupName for aisle in aisle_group}
            all_leg_ids = list(aisle_map.keys())

            all_data = DailySiteReading.objects.filter(
                associated_Site=site, leg_id__in=all_leg_ids,
                reading_for__range=[from_date.date(), till_date.date()], is_visible=True
            ).values("leg_id", "reading_for", "unit_consumption")

            data_dict = {}
            for record in all_data:
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

            return Response({"result": 1, "Dates": all_dates, "Data": data_list, "SavingData": saving_data_list})

        except Exception as err:
            return Response({"status": 500, "msg": str(err)})



# class DgFuelConsumptionDataApiUsingLoconavAPI_new(APIView):
#     '''
#     This API is used to get the DG fuel consumption data for a site on a given date. Uses the Loconav Push API for the process.
#     '''
#     permission_classes = [AllowAny]

#     @entryExit
#     def post(self, request):
#         data = request.data
#         try:
#             site_id = data.get("site_id")
#             date_str = data.get("date")
#             download_excel = data.get("download_excel", False)

#             if not site_id or not date_str:
#                 return Response({"status": 400, "msg": "site_id and date are required"})

#             site = Site.objects.get(id=site_id)
#             selected_date = datetime.strptime(date_str, "%Y/%m/%d").date()
#             vehical_number = site.partner_dg_fuel_id.upper()
            
#             # 1. Fetch Fuel Consumption Data
#             fuel_qs = DgFuelConsumptionData.objects.filter(
#                 site=site_id, created__date=selected_date
#             ).order_by("created").values("epoch_time", "fuel_consumption")
            
#             final_data = [{"x": int(i["epoch_time"]), "y": round(i["fuel_consumption"], 2)} for i in fuel_qs]
            
#             # 2. Fetch DG Unit Consumption Data
#             dg_qs = DgUnitConsumption.objects.filter(
#                 site=site_id, created__date=selected_date
#             ).values("epoch_time", "unit_consumption", "dg_fuel_consumption")
            
#             dg_unit_data, dg_fuel_data, dg_unit_per_litre = [], [], []
#             for i in dg_qs:
#                 x_val = int(i["epoch_time"])
#                 u_cons = i["unit_consumption"]
#                 f_cons = i["dg_fuel_consumption"]
                
#                 dg_unit_data.append({"x": x_val, "y": round(u_cons, 2)})
#                 if f_cons > 0:
#                     dg_fuel_data.append({"x": x_val, "y": round(f_cons, 2)})
#                     dg_unit_per_litre.append({"x": x_val, "y": round(u_cons / f_cons, 2)})

#             # 3. Fetch Alerts (Combined Refuel and Theft for optimization)
#             alerts_qs = DGAlertsData.objects.filter(
#                 Q(alert_data__contains=vehical_number) &
#                 (
#                     Q(alert_data__contains='RefuelingAlert') | Q(alert_data__contains='deviceFuelFill') |
#                     Q(alert_data__contains='theft') | Q(alert_data__contains='deviceFuelDrop')
#                 ) &
#                 Q(created__date=selected_date)
#             ).values_list('alert_data', flat=True)
            
#             refuel_data = []
#             theft_data = []

#             for i in alerts_qs:
#                 try:
#                     alert_type = i.get('alert_type') or i.get('eventType')
#                     ts = i.get('event_time') or i.get('dateTimeStamp') or i.get('timestamp')
                    
#                     if isinstance(ts, dict):
#                         ts = ts.get('value') or ts.get('time')
                    
#                     if not ts:
#                         continue
                        
#                     if isinstance(ts, (int, float)):
#                         epoch_time = float(ts)
#                     else:
#                         epoch_time = date_parser.parse(ts).timestamp()

#                     # Handle Refuel
#                     if alert_type in ['RefuelingAlert', 'deviceFuelFill']:
#                         fuel_val = i.get('refueled_in_liters') or 0
#                         if not fuel_val:
#                             f_change = i.get('fuelChange', {})
#                             if isinstance(f_change, dict):
#                                 fuel_val = f_change.get('fuel_change', 0)
#                             elif isinstance(f_change, str) and 'ltr' in f_change:
#                                 fuel_val = f_change.split('ltr')[0]
                        
#                         refuel_data.append({'x': int(epoch_time * 1000), 'y': float(fuel_val)})

#                     # Handle Theft
#                     elif alert_type in ['theft', 'deviceFuelDrop']:
#                         val = i.get('value')
#                         if val is None:
#                             f_change = i.get('fuelChange', '')
#                             if isinstance(f_change, str) and 'ltr' in f_change:
#                                 val = f_change.split('ltr')[0]
#                             elif isinstance(f_change, dict):
#                                 val = f_change.get('fuel_change', 0)
#                             else:
#                                 val = 0
#                         theft_data.append({'x': int(epoch_time * 1000), 'y': float(val)})
                        
#                 except Exception:
#                     continue

#             response_payload = {
#                 "status": 200, 
#                 "data": final_data, 
#                 "refuel_alert": {"name": "Refuel", "data": refuel_data, "type": "column"}, 
#                 "theft_alert": {"name": "Fuel Drain", "data": theft_data, "type": "column"},
#                 "dg_unit_data": {"name": "DG_Unit_Consumption", "data": dg_unit_data, "type": "column"}, 
#                 "dg_fuel_data": {"name": "DG_Fuel_Consumed", "data": dg_fuel_data, "type": "column"},
#                 "dg_unit_per_litre_data": {"name": "Dg_Unit_Per_Ltr", "data": dg_unit_per_litre, "type": "column"}
#             }

#             if download_excel:
#                 # Prepare Excel data
#                 fuel_level_df = pd.DataFrame([
#                     {"Date": datetime.fromtimestamp(i['x']/1000).strftime("%d-%b-%Y"), 
#                      "Time": datetime.fromtimestamp(i['x']/1000).strftime("%H:%M"), 
#                      "Fuel_Level": i['y']} for i in final_data
#                 ])
                
#                 dg_cons_df = pd.DataFrame([
#                     {"Time": datetime.fromtimestamp(i['x']/1000).strftime("%H:%M"), 
#                      "Unit_Consumption(KWH)": i['y'], 
#                      "Fuel_Consumed(Ltr)": next((f['y'] for f in dg_fuel_data if f['x'] == i['x']), 0)} 
#                     for i in dg_unit_data
#                 ])
                
#                 alerts_data = []
#                 for r in refuel_data:
#                     alerts_data.append({"Time": datetime.fromtimestamp(r['x']/1000).strftime("%H:%M"), "Activity": "Refuel", "Amount(Ltr)": r['y']})
#                 for t in theft_data:
#                     alerts_data.append({"Time": datetime.fromtimestamp(t['x']/1000).strftime("%H:%M"), "Activity": "Drain", "Amount(Ltr)": t['y']})
#                 alerts_df = pd.DataFrame(alerts_data)

#                 io_buffer = BytesIO()
#                 with pd.ExcelWriter(io_buffer, engine='xlsxwriter') as writer:
#                     fuel_level_df.to_excel(writer, sheet_name='Fuel Level', index=False)
#                     dg_cons_df.to_excel(writer, sheet_name='Consumption', index=False)
#                     alerts_df.to_excel(writer, sheet_name='Alerts', index=False)

#                 response = HttpResponse(
#                     io_buffer.getvalue(),
#                     content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
#                 )
#                 filename = f"DG_Fuel_Report_{site.site_name.replace(' ', '_')}_{date_str.replace('/', '-')}.xlsx"
#                 response['Content-Disposition'] = f'attachment; filename={filename}'
#                 return response

#             return Response(response_payload)
            
#         except Exception as err:
#             import traceback
#             traceback.print_exc()
#             return Response({"status": 500, "data": [], "error": str(err)})


class DgFuelConsumptionDataApiUsingLoconavAPI_new(APIView):
    '''
    This API is used to get the DG fuel consumption data for a site on a given date. Uses the Loconav Push API for the process.
    '''
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            date_str = data.get("date")
            download_excel = data.get("download_excel", False)

            if not site_id or not date_str:
                return Response({"status": 400, "msg": "site_id and date are required"})

            

            site = Site.objects.get(id=site_id)
            selected_date = datetime.strptime(date_str, "%Y/%m/%d").date()
            vehical_number = site.partner_dg_fuel_id.upper() if site.partner_dg_fuel_id else ""
            
            # 1. Fetch Fuel Consumption Data
            fuel_qs = DgFuelConsumptionData.objects.filter(
                site=site_id, created__date=selected_date
            ).order_by("created").values("epoch_time", "fuel_consumption")
            
            final_data = []
            for i in fuel_qs:
                if i["epoch_time"] is not None and i["fuel_consumption"] is not None:
                    final_data.append({"x": int(i["epoch_time"]), "y": round(i["fuel_consumption"], 2)})
            
            # 2. Fetch DG Unit Consumption Data
            dg_qs = DgUnitConsumption.objects.filter(
                site=site_id, created__date=selected_date
            ).values("epoch_time", "unit_consumption", "dg_fuel_consumption")
            
            dg_unit_data, dg_fuel_data, dg_unit_per_litre = [], [], []
            for i in dg_qs:
                if i["epoch_time"] is None or i["unit_consumption"] is None or i["dg_fuel_consumption"] is None:
                    continue
                x_val = int(i["epoch_time"])
                u_cons = i["unit_consumption"]
                f_cons = i["dg_fuel_consumption"]
                
                dg_unit_data.append({"x": x_val, "y": round(u_cons, 2)})
                if f_cons > 0:
                    dg_fuel_data.append({"x": x_val, "y": round(f_cons, 2)})
                    dg_unit_per_litre.append({"x": x_val, "y": round(u_cons / f_cons, 2)})

            # 3. Fetch Alerts (Combined Refuel and Theft for optimization)
            refuel_data = []
            theft_data = []
            
            if vehical_number:
                alerts_qs = DGAlertsData.objects.filter(
                    Q(alert_data__contains=vehical_number) &
                    (
                        Q(alert_data__contains='RefuelingAlert') | Q(alert_data__contains='deviceFuelFill') |
                        Q(alert_data__contains='theft') | Q(alert_data__contains='deviceFuelDrop')
                    ) &
                    Q(created__date=selected_date)
                ).values_list('alert_data', flat=True)
            else:
                alerts_qs = []

            for i in alerts_qs:
                try:
                    alert_type = i.get('alert_type') or i.get('eventType')
                    ts = i.get('event_time') or i.get('dateTimeStamp') or i.get('timestamp')
                    
                    if isinstance(ts, dict):
                        ts = ts.get('value') or ts.get('time')
                    
                    if not ts:
                        continue
                        
                    if isinstance(ts, (int, float)):
                        epoch_time = float(ts)
                    else:
                        epoch_time = date_parser.parse(ts).timestamp()

                    # Handle Refuel
                    if alert_type in ['RefuelingAlert', 'deviceFuelFill']:
                        fuel_val = i.get('refueled_in_liters') or 0
                        if not fuel_val:
                            f_change = i.get('fuelChange', {})
                            if isinstance(f_change, dict):
                                fuel_val = f_change.get('fuel_change', 0)
                            elif isinstance(f_change, str) and 'ltr' in f_change:
                                fuel_split = f_change.split('ltr')[0].strip()
                                fuel_val = float(fuel_split) if fuel_split else 0
                        
                        try:
                            fuel_val = float(fuel_val)
                            refuel_data.append({'x': int(epoch_time * 1000), 'y': fuel_val})
                        except ValueError:
                            pass

                    # Handle Theft
                    elif alert_type in ['theft', 'deviceFuelDrop']:
                        val = i.get('value')
                        if val is None:
                            f_change = i.get('fuelChange', '')
                            if isinstance(f_change, str) and 'ltr' in f_change:
                                val_split = f_change.split('ltr')[0].strip()
                                val = float(val_split) if val_split else 0
                            elif isinstance(f_change, dict):
                                val = f_change.get('fuel_change', 0)
                            else:
                                val = 0
                        
                        try:
                            val = float(val)
                            theft_data.append({'x': int(epoch_time * 1000), 'y': val})
                        except ValueError:
                            pass
                        
                except Exception:
                    continue

            response_payload = {
                "status": 200, 
                "data": final_data, 
                "refuel_alert": {"name": "Refuel", "data": refuel_data, "type": "column"}, 
                "theft_alert": {"name": "Fuel Drain", "data": theft_data, "type": "column"},
                "dg_unit_data": {"name": "DG_Unit_Consumption", "data": dg_unit_data, "type": "column"}, 
                "dg_fuel_data": {"name": "DG_Fuel_Consumed", "data": dg_fuel_data, "type": "column"},
                "dg_unit_per_litre_data": {"name": "Dg_Unit_Per_Ltr", "data": dg_unit_per_litre, "type": "column"}
            }



            if download_excel:
                # Prepare Excel data
                fuel_level_df = pd.DataFrame([
                    {"Date": datetime.fromtimestamp(i['x']/1000).strftime("%d-%b-%Y"), 
                     "Time": datetime.fromtimestamp(i['x']/1000).strftime("%H:%M"), 
                     "Fuel_Level": i['y']} for i in final_data
                ], columns=["Date", "Time", "Fuel_Level"])
                
                dg_cons_df = pd.DataFrame([
                    {"Time": datetime.fromtimestamp(i['x']/1000).strftime("%H:%M"), 
                     "Unit_Consumption(KWH)": i['y'], 
                     "Fuel_Consumed(Ltr)": next((f['y'] for f in dg_fuel_data if f['x'] == i['x']), 0)} 
                    for i in dg_unit_data
                ], columns=["Time", "Unit_Consumption(KWH)", "Fuel_Consumed(Ltr)"])
                
                alerts_data = []
                for r in refuel_data:
                    alerts_data.append({"Time": datetime.fromtimestamp(r['x']/1000).strftime("%H:%M"), "Activity": "Refuel", "Amount(Ltr)": r['y']})
                for t in theft_data:
                    alerts_data.append({"Time": datetime.fromtimestamp(t['x']/1000).strftime("%H:%M"), "Activity": "Drain", "Amount(Ltr)": t['y']})
                alerts_df = pd.DataFrame(alerts_data, columns=["Time", "Activity", "Amount(Ltr)"])

                io_buffer = BytesIO()
                with pd.ExcelWriter(io_buffer, engine='xlsxwriter') as writer:
                    fuel_level_df.to_excel(writer, sheet_name='Fuel Level', index=False)
                    dg_cons_df.to_excel(writer, sheet_name='Consumption', index=False)
                    alerts_df.to_excel(writer, sheet_name='Alerts', index=False)

                response = HttpResponse(
                    io_buffer.getvalue(),
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                )
                filename = f"DG_Fuel_Report_{site.site_name.replace(' ', '_')}_{date_str.replace('/', '-')}.xlsx"
                response['Content-Disposition'] = f'attachment; filename={filename}'
                return response

            return Response(response_payload)
            
        except Exception as err:
            import traceback
            traceback.print_exc()
            return Response({"status": 500, "data": [], "error": str(err)})


class DgFuelConsumptionDataCustomRangeApiUsingPushAPIs(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            from_date = data.get("from_date")
            end_date = data.get("end_date")
            site = Site.objects.get(id=site_id)
            vehical_number = site.partner_dg_fuel_id.upper()
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%Y-%m-%d")
            final_data = []
            fuel_data = DgFuelConsumptionData.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                             created__date__lte=end_date.date()).order_by("created")
            for i in fuel_data:
                final_data.append({"x": int(i.epoch_time), "y": round(i.fuel_consumption, 2)})
            dg_data = DgUnitConsumption.objects.filter(site=site_id, created__date__gte=from_date.date(),
                                                       created__date__lte=end_date.date())
            logger.debug(final_data)
            logger.debug(dg_data)
            print("dg data: ", dg_data)
            dg_unit_data = []
            dg_fuel_data = []
            dg_unit_per_litre = []
            if dg_data.exists():
                logger.debug("enside dg data conditions")
                for i in dg_data:
                    logger.debug("i value: ", i)
                    dg_unit_data.append({"x": int(i.epoch_time), "y": round(i.unit_consumption, 2)})
                    if i.dg_fuel_consumption > 0:
                        dg_fuel_data.append({"x": int(i.epoch_time), "y": i.dg_fuel_consumption})
                        dg_unit_per_litre.append(
                            {"x": int(i.epoch_time), "y": round(i.unit_consumption / i.dg_fuel_consumption, 2)})
            refuel_data = []
            theft_data = []
            refueling_alerts = DGAlertsData.objects.filter(
                Q(alert_data__contains = vehical_number) &
                (Q(alert_data__contains = 'RefuelingAlert') | Q(alert_data__contains = 'deviceFuelFill')) &
                Q(created__date__gte = from_date.date()) &
                Q(created__date__lte = end_date.date())
            )
            refueling_alerts = [i.alert_data for i in refueling_alerts]
            for i in refueling_alerts:
                epoch_time = datetime.strptime(i.get('event_time')[:-6], "%Y-%m-%dT%H:%M:%S.%f").timestamp() if i.get('event_time','') != '' else datetime.strptime(i.get('dateTimeStamp','')[:-6], "%Y-%m-%dT%H:%M:%S.%f").timestamp()
                refuel_data.append({'x': int(epoch_time) * 1000, 'y': float(i.get('refueled_in_liters', i.get('fuelChange', '').split('ltr')[0]))})

            theft_alerts = DGAlertsData.objects.filter(
                Q(alert_data__contains = vehical_number) &
                (Q(alert_data__contains = 'theft') | Q(alert_data__contains = 'deviceFuelDrop')) &
                Q(created__date__gte = from_date.date()) &
                Q(created__date__lte = end_date.date())
            )
            theft_alerts = [i.alert_data for i in theft_alerts]
            for i in theft_alerts:
                epoch_time = i.timestamp if i.get('timestamp','') != '' else datetime.strptime(i.get('dateTimeStamp','')[:-6], "%Y-%m-%dT%H:%M:%S.%f").timestamp()
                theft_data.append({'x': epoch_time * 1000, 'y': float(i.get('value', i.get('fuelChange', '').split('ltr')[0]))})

            refuel_final_data = {"name": "Refuel", "data": refuel_data, "type": "column"}
            theft_final_data = {"name": "Fuel Drain", "data": theft_data, "type": "column"}
            dg_unit_final_data = {"name": "DG_Unit_Consumption", "data": dg_unit_data, "type": "column"}
            dg_fuel_final_data = {"name": "DG_Fuel_Consumed", "data": dg_fuel_data, "type": "column"}
            dg_unit_per_litre_data = {"name": "Dg_Unit_Per_Ltr", "data": dg_unit_per_litre, "type": "column"}
            return Response(
                {"status": 200, "data": final_data, "refuel_alert": refuel_final_data, "theft_alert": theft_final_data,
                 "dg_unit_data": dg_unit_final_data, "dg_fuel_data": dg_fuel_final_data,
                 "dg_unit_per_litre_data": dg_unit_per_litre_data})
        except Exception as err:
            return Response({"status": 500, "data": [], "error": str(err)})




class DgAlertsPushInterface(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        try:
            interface_id = request.headers.get('X-Interface-Id')
            map_of_interfaces = {
                'Roadcaste' : 'ARGNDG390021',
                'AviconnTesting' : '172290'
            }
            if(interface_id not in map_of_interfaces.values()):
                raise AttributeError("Invalid Interface ID, the Data can't be processed")
            data = request.data
            DGAlertsData.objects.create(alert_data=data)
            return Response({"status": 200, "message": "DG Fuel Alert Recieved"})
        except AttributeError as e:
            return Response({'message' : str(e), "status" : 400})
        except Exception as e:
            return Response({'message' : str(e), "status" : 500})

class DownloadExcel_new(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = int(data.get("site_id"))
            site_id = 29 if site_id == 34 else site_id
            user_type = int(data.get("user_type", ''))

            start_date = datetime.strptime(data.get("from_date"), "%Y-%m-%d")
            end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")

            # Fetch aisles more efficiently
            if user_type == 1:
                aisles = AisleGroup.objects.filter(site=site_id)
            else:
                if int(data.get('site_id')) == 34:
                    aisles = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 710, 276])
                else:
                    aisles = AisleGroup.objects.filter(site=site_id, is_visible=True)

            aisle_names = [aisle.aisleGroupName for aisle in aisles]
            leg_ids = [aisle.attached_leg_id for aisle in aisles]

            # Fetch all relevant readings in one query
            readings = DailySiteReading.objects.filter(
                associated_Site=site_id,
                is_visible = True,
                leg_id__in=leg_ids, 
                reading_for__range=[start_date, end_date]
            ).values('leg_id', 'reading_for').annotate(total_consumption=Sum('unit_consumption'))

            # Organize readings by date and leg_id
            readings_dict = defaultdict(lambda: defaultdict(float))
            for reading in readings:
                date = reading['reading_for'].strftime("%d-%b-%Y")
                readings_dict[date][reading['leg_id']] = round(reading['total_consumption'], 2)

            # Prepare data for DataFrame
            header = ["Date", "TotalConsumption"] + aisle_names
            data_rows = []

            for i in range((end_date - start_date).days + 1):
                current_date = (start_date + timedelta(days=i)).strftime("%d-%b-%Y")
                daily_readings = readings_dict.get(current_date, {})
                row = [current_date]
                total = 0
                for leg_id in leg_ids:
                    consumption = daily_readings.get(leg_id, 0)
                    total += consumption
                    row.append(consumption)
                row.insert(1, total)
                data_rows.append(row)

            # Create CSV from DataFrame
            df = pd.DataFrame(data_rows, columns=header)
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename=output.csv'
            df.to_csv(response, index=False)

            return response

        except Exception as e:
            return Response({'message' : str(e)})


# class DGFuelDataExcelExport(APIView):
#     permission_classes = [AllowAny]

#     def post(self, request):
#         try:
#             data = request.data
#             site_id = data.get("site_id")
#             site = Site.objects.get(id=site_id)
#             from_date = datetime.strptime(data.get("start_date"), "%Y-%m-%d")
#             end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")
#             vehical_number = site.partner_dg_fuel_id.upper()
#             dg_fuel_values = DgFuelConsumptionData.objects.filter(site = site_id, created__date__range = (from_date, end_date)).annotate(minute_bucket=TruncMinute('created')).values('minute_bucket').annotate(Fuel_Level=Avg('fuel_consumption')).order_by('-minute_bucket')

#             fuel_absolute_data = [
#                 {
#                     "Date": i['minute_bucket'].strftime("%d-%b-%Y"),
#                     "Time": i['minute_bucket'].strftime("%H:%M"),
#                     "Fuel_Level": round(i['Fuel_Level'], 2) if i['Fuel_Level'] is not None else 0,
#                 }
#                 for i in dg_fuel_values
#             ]

#             dg_data = DgUnitConsumption.objects.filter(
#                 site=site_id,
#                 created__date__range=(from_date.date(), end_date.date())
#             ).order_by('-created')

#             dg_fuel_unit_data = [
#                 {
#                     "Start_Date": i.dg_start_date.strftime("%d-%b-%Y"),
#                     "Start_Time": f"{i.dg_start_date.hour}:{i.dg_start_date.minute}",
#                     "End_Date": i.dg_end_date.strftime("%d-%b-%Y"),
#                     "End_Time": f"{i.dg_end_date.hour}:{i.dg_end_date.minute}",
#                     "DG_Fuel_Consumed(Litres)": i.dg_fuel_consumption,
#                     "DG_Unit_Consumption(KWH)": i.unit_consumption,
#                     "DG_Unit_Per_Ltr": round(i.unit_consumption / i.dg_fuel_consumption, 2) if i.dg_fuel_consumption > 0 else 0,
#                 }
#                 for i in dg_data
#             ]

#             alerts = DGAlertsData.objects.filter(
#                 Q(alert_data__contains=vehical_number),
#                 Q(created__date__range=(from_date.date(), end_date.date()))
#             )
#             refuel_theft_data = [
#                 {
#                     "Date": datetime.strptime(i.get('event_time', i.get('dateTimeStamp')[:-6]), "%Y-%m-%dT%H:%M:%S.%f").strftime("%d-%b-%Y"),
#                     "Time": datetime.strptime(i.get('event_time', i.get('dateTimeStamp')[:-6]), "%Y-%m-%dT%H:%M:%S.%f").strftime("%H:%M"),
#                     "Activity": "Refuel" if i.get('alert_type', i.get('eventType')) in ['RefuelingAlert', 'deviceFuelFill'] else "Theft",
#                     "Fuel(in Litres)": round(float(i.get('refueled_in_liters', i.get('fuelChange').split('ltr')[0])), 2),
#                 }
#                 for i in [alert.alert_data for alert in alerts]
#                 if i.get('alert_type', i.get('eventType')) in ['RefuelingAlert', 'theft', 'deviceFuelDrop', 'deviceFuelFill']
#             ]

#             current_date = datetime.now().strftime("%d-%B-%Y")
#             io_buffer = BytesIO()
#             with pd.ExcelWriter(io_buffer, engine='xlsxwriter') as writer:
#                 pd.DataFrame(fuel_absolute_data).to_excel(writer, sheet_name='Fuel Level', index=False)
#                 pd.DataFrame(dg_fuel_unit_data).to_excel(writer, sheet_name='DG Fuel & Unit Consumption', index=False)
#                 pd.DataFrame(refuel_theft_data).to_excel(writer, sheet_name='DG Refuel & Theft Data', index=False)

#             response = HttpResponse(
#                 io_buffer.getvalue(),
#                 content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
#             )
#             response['Content-Disposition'] = f'attachment; filename=Report_DG_Fuel_Unit_Trend_{current_date}.xlsx'
#             return response

#         except Exception as err:
#             return Response({"status": 500, "msg": str(err)})

class DGFuelDataExcelExport(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")
            site = Site.objects.get(id=site_id)
            from_date = datetime.strptime(data.get("start_date"), "%Y-%m-%d")
            end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")
            vehical_number = site.partner_dg_fuel_id.upper()
            
            dg_fuel_values = DgFuelConsumptionData.objects.filter(
                site=site_id, created__date__range=(from_date, end_date)
            ).annotate(minute_bucket=TruncMinute('created')).values('minute_bucket').annotate(
                Fuel_Level=Avg('fuel_consumption')
            ).order_by('-minute_bucket')

            fuel_absolute_data = [
                {
                    "Date": i['minute_bucket'].strftime("%d-%b-%Y"),
                    "Time": i['minute_bucket'].strftime("%H:%M"),
                    "Fuel_Level": round(i['Fuel_Level'], 2) if i['Fuel_Level'] is not None else 0,
                }
                for i in dg_fuel_values
            ]

            dg_data = DgUnitConsumption.objects.filter(
                site=site_id,
                created__date__range=(from_date.date(), end_date.date())
            ).order_by('-created')

            dg_fuel_unit_data = [
                {
                    "Start_Date": i.dg_start_date.strftime("%d-%b-%Y"),
                    "Start_Time": i.dg_start_date.strftime("%H:%M"),
                    "End_Date": i.dg_end_date.strftime("%d-%b-%Y"),
                    "End_Time": i.dg_end_date.strftime("%H:%M"),
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
            
            refuel_theft_data = []
            for alert in alerts:
                i = alert.alert_data
                try:
                    alert_type = i.get('alert_type') or i.get('eventType')
                    if alert_type not in ['RefuelingAlert', 'theft', 'deviceFuelDrop', 'deviceFuelFill']:
                        continue
                        
                    ts_raw = i.get('event_time') or i.get('dateTimeStamp') or i.get('timestamp')
                    if isinstance(ts_raw, dict):
                        ts_raw = ts_raw.get('value') or ts_raw.get('time')
                    
                    if not ts_raw:
                        continue
                    
                    if isinstance(ts_raw, (int, float)):
                        dt = datetime.fromtimestamp(ts_raw if ts_raw > 1e11 else ts_raw) # Handle ms vs s roughly
                        if ts_raw > 1e11: dt = datetime.fromtimestamp(ts_raw/1000)
                    else:
                        dt = date_parser.parse(ts_raw)
                        
                    activity = "Refuel" if alert_type in ['RefuelingAlert', 'deviceFuelFill'] else "Theft"
                    
                    fuel_val = i.get('refueled_in_liters') or i.get('value')
                    if fuel_val is None:
                        f_change = i.get('fuelChange', '')
                        if isinstance(f_change, str) and 'ltr' in f_change:
                            fuel_val = f_change.split('ltr')[0]
                        elif isinstance(f_change, dict):
                            fuel_val = f_change.get('fuel_change', 0)
                        else:
                            fuel_val = 0
                            
                    refuel_theft_data.append({
                        "Date": dt.strftime("%d-%b-%Y"),
                        "Time": dt.strftime("%H:%M"),
                        "Activity": activity,
                        "Fuel(in Litres)": round(float(fuel_val), 2)
                    })
                except Exception:
                    continue

            current_date = datetime.now().strftime("%d-%B-%Y")
            io_buffer = BytesIO()
            with pd.ExcelWriter(io_buffer, engine='xlsxwriter') as writer:
                if fuel_absolute_data:
                    pd.DataFrame(fuel_absolute_data).to_excel(writer, sheet_name='Fuel Level', index=False)
                if dg_fuel_unit_data:
                    pd.DataFrame(dg_fuel_unit_data).to_excel(writer, sheet_name='DG Fuel & Unit Consumption', index=False)
                if refuel_theft_data:
                    pd.DataFrame(refuel_theft_data).to_excel(writer, sheet_name='DG Refuel & Theft Data', index=False)

            response = HttpResponse(
                io_buffer.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = f'attachment; filename=Report_DG_Fuel_Unit_Trend_{current_date}.xlsx'
            return response

        except Exception as err:
            import traceback
            traceback.print_exc()
            return Response({"status": 500, "msg": str(err)})

class PowerDistributionPieChartV2(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        try:
            site_id = request.data.get('siteId')
            print(site_id)
            if not site_id:
                return Response({"error": "SiteID is required"}, status=status.HTTP_400_BAD_REQUEST)

            current_date = datetime.now()

            # 1. Sum per leg first 
            readings = (
                DailySiteReading.objects
                .filter(
                    associated_Site=site_id,
                    reading_for__year=current_date.year,
                    reading_for__month=current_date.month
                )
                .values('leg_id')
                .annotate(total_units=Sum('unit_consumption'))
            )
            print(readings)

            leg_ids = [r['leg_id'] for r in readings]

            aisle_groups = {
                ag.attached_leg_id: ag.aisleGroupName
                for ag in AisleGroup.objects.filter(attached_leg_id__in=leg_ids)
            }

            # 2. Aggregate by source name
            source_totals = {}
            for r in readings:
                leg_id = r['leg_id']
                source_name = aisle_groups.get(leg_id, str(leg_id))
                source_totals[source_name] = source_totals.get(source_name, 0) + (r['total_units'] or 0)

            # 3. Build datalist 
            datalist = [
                {"name": name, "data": total}
                for name, total in source_totals.items()
            ]

            total_sum = sum(item["data"] for item in datalist)
            finalData = []

            for item in datalist:
                percentage = item["data"] * 100 / total_sum if total_sum else 0
                finalData.append({
                    "name": item["name"],
                    "data": round(percentage, 2)
                })

            response_data = {
                "result": 1,
                "data": finalData,
                "current_month": current_date.strftime("%b-%Y")
            }
            return Response(response_data)

        except Exception as e:
            return Response({"msg": str(e)})


class PowerSource(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        try:
            site = data.get('site_id')
            sources = AisleGroup.objects.filter(site_id = site, is_this_power_source = True)

            response = [
                {
                    "id" : i.id,
                    "aisleGroupName" : i.aisleGroupName,
                    "powerSource" : i.power_source
                }
                for i in sources
            ]
            return Response(
                {
                    "data" : response,
                    "result": 1,
                },
                status=200
            )
        except Exception as err:
            return Response({"error" : str(err), "message" : "Internal Server Error"}, status = 500)

class LoadDataApi(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        try:
            selected_date = datetime.strptime(data.get('date'), "%Y/%m/%d")
            hourlyLoadData = HourlyLoadData.objects.filter(aisle_group_id=data.get('aisle_id'), created__date=selected_date.date()).order_by("created").values("epoch_time", "load_data", "aisle_group__load_graph_color")

            if(hourlyLoadData.exists()):
                res = [
                    {
                        "x": int(i["epoch_time"]),
                        "y": round(i["load_data"] / 1000, 3),
                        "color": i["aisle_group__load_graph_color"]
                    }
                    for i in hourlyLoadData
                ]
                return Response({"status": 200, "data": res})
            else:
                res = [{"x" : 0, "y" : int(datetime.now().timestamp())}]
                return Response({"status": 404, "data": res})
        except Exception as err:
            return Response({"status": 500, "message": "Internal Server Error", "error": str(err)})


class LoadDataApiMultipleSource(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        date_str = data.get('date')
        site_id = data.get('site_id')

        if not date_str or not site_id:
            return Response({"error": "Missing 'date' or 'site_id'"}, status=400)

        try:
            selected_date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response({"error": "Invalid date format. Expected YYYY/MM/DD"}, status=400)

        try:
            aisle_groups = AisleGroup.objects.filter(site_id=site_id).values("id", "aisleGroupName")
            aisle_group_ids = [g['id'] for g in aisle_groups]

            hourly_data = HourlyLoadData.objects.filter(
                aisle_group_id__in=aisle_group_ids,
                created__date=selected_date.date()
            ).order_by("created").values(
                "epoch_time", "load_data",
                "aisle_group__load_graph_color",
                "aisle_group__aisleGroupName"
            )

            grouped_data = defaultdict(list)
            for row in hourly_data:
                name = row['aisle_group__aisleGroupName']
                grouped_data[name].append({
                    "x": int(row["epoch_time"]),
                    "y": round(row["load_data"] / 1000, 3),
                    "color": row["aisle_group__load_graph_color"]
                })

            response_data = [
                {
                    group["aisleGroupName"]: grouped_data.get(group["aisleGroupName"], [])
                }
                for group in aisle_groups
            ]

            return Response({"data": response_data, "status": 200})
        except Exception as err:
            return Response(
                {"error": str(err), "message": "Internal Server Error"},
                status=500
            )


class LoadDataApiMultipleSourceV2(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        date_str = data.get('date')
        site_id = data.get('site_id')

        if not date_str or not site_id:
            return Response({"error": "Missing 'date' or 'site_id'"}, status=400)

        try:
            selected_date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response({"error": "Invalid date format. Expected YYYY/MM/DD"}, status=400)

        try:
            aisle_groups = AisleGroup.objects.filter(site_id=site_id).values("id", "aisleGroupName")
            aisle_group_ids = [g['id'] for g in aisle_groups]

            hourly_data = HourlyLoadData.objects.filter(
                aisle_group_id__in=aisle_group_ids,
                created__date=selected_date.date()
            ).order_by("created").values(
                "epoch_time",
                "load_data",
                "aisle_group__load_graph_color",
                "aisle_group__aisleGroupName"
            )

            grouped_data = defaultdict(list)
            for row in hourly_data:
                name = row['aisle_group__aisleGroupName']
                grouped_data[name].append({
                    "x": int(row["epoch_time"]),
                    "y": round(row["load_data"] / 1000, 3),
                    "color": row["aisle_group__load_graph_color"]
                })

            GAP_THRESHOLD = 300000  # 5 min

            filled_grouped_data = {}
            for name, points in grouped_data.items():
                filled = []
                for i, point in enumerate(points):
                    filled.append(point)

                    if i + 1 < len(points):
                        next_point = points[i + 1]
                        gap = next_point["x"] - point["x"]

                        if gap > GAP_THRESHOLD:
                            # Instead of thousands of zeros, insert a gap marker
                            filled.append({
                                "from": point["x"] + 1,
                                "to": next_point["x"] - 1,
                                "y": 0,
                                "color": point["color"]
                            })

                filled_grouped_data[name] = filled

            response_data = [
                {group["aisleGroupName"]: filled_grouped_data.get(group["aisleGroupName"], [])}
                for group in aisle_groups
            ]

            return Response({"data": response_data, "status": 200})

        except Exception as err:
            return Response(
                {"error": str(err), "message": "Internal Server Error"},
                status=500
            )


class LiveDataApi(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        site_id = data.get('site_id', 0)
        epoch_time = data.get('epoch_time', 0)
        try:
            load_data = RawLoadData.objects.filter(aisle_group__site_id = site_id, epoch_time__gt = epoch_time).prefetch_related('aisle_group')
            grouped_data = defaultdict(list)
            for obj in load_data:
                grouped_data[obj.aisle_group.aisleGroupName].append({
                    "load": obj.load_data/1000,
                    "epoch": obj.epoch_time
                })
            response = {"data": dict(grouped_data)}
            return Response(response)
        except Exception as err:
            return Response({"message" : str(err)})



from django.db.models import Sum
from django.db.models.functions import TruncMonth
from dateutil.relativedelta import relativedelta

class DgFuelMonthlyTrend_test(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = data.get("site_id")

            # Special case: site_id 124
            if site_id == int(124):
                return DGfuelMonthlyTrendMultipleAisles(124)

            # Find mains and DG aisles
            aisle_group = AisleGroup.objects.filter(site=site_id)
            mains_aisle, dg_aisle = 0, 0
            for aisle in aisle_group:
                if aisle.power_source == 0:
                    mains_aisle = aisle.attached_leg_id
                elif aisle.power_source == 1:
                    dg_aisle = aisle.attached_leg_id

            if not mains_aisle and not dg_aisle:
                return Response({"status": 400, "msg": "aisle not matched"})

            # Build month list for last 12 months
            current_date = datetime.now().replace(day=1)
            month_list = [(current_date - relativedelta(months=i)) for i in range(11, -1, -1)]
            month_labels = [m.strftime("%b-%Y") for m in month_list]

            # ---- Fetch data in bulk ----
            start_date = month_list[0].replace(day=1)
            end_date = (current_date + relativedelta(months=1))  # exclusive upper bound

            # DG fuel consumption (from DgUnitConsumption)
            dg_fuel_raw = (
                DgUnitConsumption.objects
                .filter(site_id=site_id, created__gte=start_date, created__lt=end_date)
                .annotate(month=TruncMonth("created"))
                .values("month")
                .annotate(total=Sum("dg_fuel_consumption"))
                .order_by("month")
            )
            """dg_fuel_raw = (
                DgFuelConsumptionData.objects
             .filter(
                site_id=site_id,
                created__gte=start_date,
                created__lt=end_date
                )
            .annotate(month=TruncMonth("created"))
            .values("month")
            .annotate(total=Sum("fuel_consumption"))
             .order_by("month")
            )"""
            dg_fuel_map = {row["month"].strftime("%b-%Y"): row["total"] or 0 for row in dg_fuel_raw}

            # Mains unit consumption
            mains_units_raw = (
                DailySiteReading.objects
                .filter(associated_Site=site_id, aisle_group=mains_aisle,
                        reading_for__gte=start_date, reading_for__lt=end_date)
                .annotate(month=TruncMonth("reading_for"))
                .values("month")
                .annotate(total=Sum("unit_consumption"))
                .order_by("month")
            )
            mains_units_map = {row["month"].strftime("%b-%Y"): row["total"] or 0 for row in mains_units_raw}

            # DG unit consumption
            dg_units_raw = (
                DailySiteReading.objects
                .filter(associated_Site=site_id, aisle_group=dg_aisle,
                        reading_for__gte=start_date, reading_for__lt=end_date)
                .annotate(month=TruncMonth("reading_for"))
                .values("month")
                .annotate(total=Sum("unit_consumption"))
                .order_by("month")
            )
            dg_units_map = {row["month"].strftime("%b-%Y"): row["total"] or 0 for row in dg_units_raw}

            # ---- Build final aligned lists ----
            dg_fuel_consumption_list = [round(dg_fuel_map.get(label, 0), 2) for label in month_labels]
            mains_unit_consumption_list = [round(mains_units_map.get(label, 0), 2) for label in month_labels]
            dg_unit_consumption_list = [round(dg_units_map.get(label, 0), 2) for label in month_labels]

            return Response({
                "status": 200,
                "months": month_labels,
                "dg_fuel_monthly": dg_fuel_consumption_list,
                "mains_unit_consumption_monthly": mains_unit_consumption_list,
                "dg_unit_consumption_monthly": dg_unit_consumption_list,
            })

        except Exception as err:
            return Response({"status": 500, "msg": str(err)})


class LoadDataExcelDownloadMonthlyRange(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        try:
            site_id = data.get("site_id")
            from_date = data.get("from_date")
            end_date = data.get("end_date")
            graph_type = data.get("graph_type")
            
            # Parse dates
            start_date = datetime.strptime(from_date, "%Y/%m/%d")
            till_date = datetime.strptime(end_date, "%Y/%m/%d")
            
            # Get site name for filename
            try:
                site = Site.objects.get(id=site_id)
                site_name = site.site_name.replace(' ', '').replace('/', '')  # Clean site name for filename
            except Site.DoesNotExist:
                site_name = f"Site_{site_id}"
            
            date_array = []
            data_array = []
            power_source = []
            
            if graph_type == "0":
                # Hourly data for date range
                final_data = HourlyLoadData.objects.filter(
                    site=site_id, 
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date()
                ).order_by("created")
            elif graph_type == "1":
                # Daily data for date range
                final_data = DailyLoadData.objects.filter(
                    site=site_id, 
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date()
                ).order_by("created")
            elif graph_type == "2":
                # Custom date range daily data - uses exact date range provided
                final_data = DailyLoadData.objects.filter(
                    site=site_id, 
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date()
                ).order_by("created")
            elif graph_type == "3":
                # MainsDg data for date range
                final_data = MainsDgLoadData.objects.filter(
                    site=site_id,
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date()
                ).order_by("created")
            elif graph_type == "4":
                # Raw data for date range
                final_data = RawLoadData.objects.filter(
                    site=site_id, 
                    created__date__gte=start_date.date(),
                    created__date__lte=till_date.date()
                ).order_by("created")
            else:
                # Monthly data for date range
                final_data = MonthlyLoadSharePercentage.objects.filter(
                    site=site_id,
                    created_on__date__gte=start_date.date(),
                    created_on__date__lte=till_date.date()
                ).order_by("created_on")
            
            if final_data:
                for i in final_data:
                    if hasattr(i, 'load_data'):
                        load_data = i.load_data / 1000
                    elif hasattr(i, 'total_load'):
                        load_data = i.total_load / 1000
                    else:
                        load_data = 0
                        
                    if load_data > 0:
                        if hasattr(i, 'created'):
                            date_array.append(i.created.strftime("%d %b, %Y %H:%M:%S"))
                        elif hasattr(i, 'created_on'):
                            date_array.append(i.created_on.strftime("%d %b, %Y %H:%M:%S"))
                        
                        data_array.append(round(load_data, 3))
                        
                        if (graph_type == "3" or graph_type == "4") and hasattr(i, 'aisle_group'):
                            power_source.append(i.aisle_group.aisleGroupName)
                
                if graph_type == "3" or graph_type == "4":
                    df = pd.DataFrame({
                        "Date": date_array, 
                        "Load Data(KW)": data_array, 
                        "Power_Source": power_source
                    })
                else:
                    df = pd.DataFrame({
                        "Date": date_array, 
                        "Load Data(KW)": data_array
                    })
                
                file_name = f"{site_name}load_data_monthly_range{from_date.replace('/', '')}_to{end_date.replace('/', '_')}.csv"
                response = HttpResponse(content_type='text/csv')
                response['filename'] = file_name
                response['Content-Disposition'] = f'attachment; filename={file_name}'
                df.to_csv(response, index=False)
                return response
            else:
                return Response({
                    "status": 500, 
                    "data": [], 
                    "msg": "No data found for the selected date range and graph type"
                })
                
        except Exception as err:
            print(err)
            return Response({"status": 500, "data": [], "msg": str(err)})


class EnergySavingMonthlyBarChartTestVB(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        data = request.data
        site_id = int(data.get("site_id", 0))

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

            # Add is_visible condition only if user_type is not 1 and the site is not 34
            is_visible = False if user_type == 1 else True
            if user_type == 1:
                aisle_group = AisleGroup.objects.filter(virtual_siteID = site)
            else:
                aisle_group = AisleGroup.objects.filter(virtual_siteID = site, is_visible = True)
            print(aisle_group)
            aisle_map = {aisle.attached_leg_id: aisle.aisleGroupName for aisle in aisle_group}
            all_leg_ids = list(aisle_map.keys())
            
            all_data = DailySiteReading.objects.filter(
                aisle_group__virtual_siteID=site, leg_id__in=all_leg_ids,
                reading_for__range=[from_date.date(), till_date.date()], is_visible=True
            ).values("leg_id", "reading_for", "unit_consumption")
            print(all_data)
            
            data_dict = {}
            for record in all_data:
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
                latest_baseline_values = SiteBaseline.objects.filter(leg_id__in=all_leg_ids)
                print(latest_baseline_values)
                
                for date in all_dates:
                    baseline_value = latest_baseline_values.filter(baseline_from__lte=date).filter(Q(baseline_to__gte=date) | Q(baseline_to__isnull=True)).aggregate(Sum('baseline_value'))['baseline_value__sum'] or 0
                    baseline_list.append(round(baseline_value, 2))
                
                data_list.append({"name": "baseline", "data": baseline_list, "type": "spline"})
            
            return Response({"result": 1, "Dates": all_dates, "Data": data_list, "SavingData": saving_data_list})
        
        except Exception as err:
            return Response({"status": 500, "msg": str(err)})

# class EnergySavingMonthlyBarChartTestVB(APIView):
#     permission_classes = [AllowAny]
    
#     def post(self, request):
#         from django.core.cache import cache
#         from dateutil.relativedelta import relativedelta

#         data = request.data
#         site_id = int(data.get("site_id", 0))

#         try:
#             site = Site.objects.get(id=site_id)
#             from_date = datetime.strptime(data.get("from_date", ""), "%Y/%m/%d")
#             till_date = datetime.strptime(data.get("till_date", ""), "%Y/%m/%d")
#             user_type = int(data.get("user_type", 0))
            
#             # Determine total days and generate date list (Ascending order)
#             total_days = (till_date - from_date).days + 1
#             all_dates = [(till_date - timedelta(days=i)).date() for i in range(total_days)]
#             all_dates.reverse()

#             # Add is_visible condition only if user_type is not 1 and the site is not 34 (logic preserved from original)
#             # Original code: is_visible = False if user_type == 1 else True (var not used directly in filter below but logic implies)
#             if user_type == 1:
#                 aisle_group = AisleGroup.objects.filter(virtual_siteID = site)
#             else:
#                 aisle_group = AisleGroup.objects.filter(virtual_siteID = site, is_visible = True)
            
#             aisle_map = {aisle.attached_leg_id: aisle.aisleGroupName for aisle in aisle_group}
#             all_leg_ids = list(aisle_map.keys())
            
#             all_data = []

#             # Caching Strategy:
#             # - Iterate through months covered by the requested range.
#             # - If a month is strictly in the past (before current month), try to fetch from cache.
#             # - If cache miss (or current month), fetch from DB.
#             # - Combine all data.

#             current_date_obj = datetime.now().date()
#             current_month_start = current_date_obj.replace(day=1)
            
#             loop_date = from_date.date()
#             end_date = till_date.date()

#             while loop_date <= end_date:
#                 # Boundaries of the month for the current loop_date
#                 month_start = loop_date.replace(day=1)
#                 next_month = month_start + relativedelta(months=1)
#                 month_end = next_month - timedelta(days=1)

#                 # Determine the actual chunk of days needed from this month
#                 chunk_start = max(loop_date, month_start)
#                 chunk_end = min(end_date, month_end)

#                 # Check if this month is fully in the past
#                 is_previous_month = month_start < current_month_start

#                 if is_previous_month:
#                     # Generic cache key for the site and month (ignoring user_type specific leg selection filtering which happens later)
#                     cache_key = f"daily_reading_site_{site_id}_{month_start.year}_{month_start.month}"
#                     cached_month_data = cache.get(cache_key)

#                     if cached_month_data is None:
#                         # Fetch ALL visible readings for the site for this month and cache them
#                         cached_month_data = list(DailySiteReading.objects.filter(
#                             aisle_group__virtual_siteID=site,
#                             reading_for__year=month_start.year,
#                             reading_for__month=month_start.month,
#                             is_visible=True
#                         ).values("leg_id", "reading_for", "unit_consumption"))
                        
#                         # Cache for a long duration (e.g. 30 days) as past data shouldn't change
#                         cache.set(cache_key, cached_month_data, timeout=60 * 60 * 24 * 30)
                    
#                     # Filter the cached data for the specific valid legs and date range of this request
#                     for record in cached_month_data:
#                         r_date = record['reading_for']
#                         # Handle potential date string format from cache serialization
#                         if isinstance(r_date, str):
#                             r_date = datetime.strptime(r_date, "%Y-%m-%d").date()
#                             # Update record to have date object for consistency
#                             record['reading_for'] = r_date 
#                         elif isinstance(r_date, datetime):
#                             r_date = r_date.date()
                        
#                         if chunk_start <= r_date <= chunk_end and record['leg_id'] in all_leg_ids:
#                             all_data.append(record)
                
#                 else:
#                     # Current month or future: Fetch fresh data from DB
#                     fresh_data = DailySiteReading.objects.filter(
#                         aisle_group__virtual_siteID=site,
#                         leg_id__in=all_leg_ids,
#                         reading_for__range=[chunk_start, chunk_end],
#                         is_visible=True
#                     ).values("leg_id", "reading_for", "unit_consumption")
#                     all_data.extend(fresh_data)
                
#                 # Move loop to the start of the next month
#                 loop_date = next_month
            
#             # Process collected data into the required format
#             data_dict = {}
#             for record in all_data:
#                 leg_id = record["leg_id"]
#                 reading_for = record["reading_for"]
#                 unit_consumption = record["unit_consumption"]
                
#                 # Ensure date object
#                 if isinstance(reading_for, str):
#                     reading_for = datetime.strptime(reading_for, "%Y-%m-%d").date()
#                 elif isinstance(reading_for, datetime):
#                     reading_for = reading_for.date()
                
#                 aisle_name = aisle_map.get(leg_id, "Unknown")
                
#                 if reading_for in all_dates:
#                     idx = all_dates.index(reading_for)
#                     data_dict.setdefault(aisle_name, [0] * total_days)[idx] = round(unit_consumption, 2)

#             data_list = [{"name": k, "data": v, "type": "column"} for k, v in data_dict.items()]
#             saving_data_list = data_list.copy()

#             baseline_list = []
#             if site.is_live:
#                 baseline_filter = Q(associated_site_id=site_id, leg_id__in=all_leg_ids)
#                 latest_baseline_values = SiteBaseline.objects.filter(leg_id__in=all_leg_ids)
                
#                 for date in all_dates:
#                     baseline_value = latest_baseline_values.filter(baseline_from__lte=date).filter(Q(baseline_to__gte=date) | Q(baseline_to__isnull=True)).aggregate(Sum('baseline_value'))['baseline_value__sum'] or 0
#                     baseline_list.append(round(baseline_value, 2))
                
#                 data_list.append({"name": "baseline", "data": baseline_list, "type": "spline"})
            
#             return Response({"result": 1, "Dates": all_dates, "Data": data_list, "SavingData": saving_data_list})
        
#         except Exception as err:
#             return Response({"status": 500, "msg": str(err)})


# class EnergySavingsHourlyBarChartVB(APIView):
#     '''
#     This API is used to get the hourly energy consumption data for a site on a given date. (For Savings Only)
#     '''
#     permission_classes = [AllowAny]
#     def post(self, request):
#         data = request.data
#         site_id = data.get("site_id", "")
#         start_time = datetime.now()
#         print("function start time is:", start_time)

#         try:
#             site = Site.objects.get(id=site_id)
#         except Site.DoesNotExist:
#             return Response({"result": 0, "msg": "Site not found"}, status=404)

#         date_str = data.get("date", "")
#         try:
#             date = datetime.strptime(date_str, "%Y/%m/%d")
#         except ValueError:
#             return Response({"result": 0, "msg": "Invalid date format"}, status=400)


#         hourList = ["{:02d}:00".format(i) for i in range(24)]
#         dataList = []
#         savingList = []

#         all_leg_ids = DailySiteReading.objects.filter(
#             aisle_group__virtual_siteID_id = site_id, reading_for=date
#         ).values_list("leg_id", flat=True).distinct()
#         print(all_leg_ids)
#         oneDayData = HourlySiteReading.objects.filter(
#             aisle_group__virtual_siteID_id = site_id, reading_from__date=date, is_visible=True
#         ).select_related('aisle_group')
#         print(oneDayData)
#         # Group by leg_id and hour to reduce the number of iterations
#         hourly_data_map = {
#             (item.leg_id, item.reading_from.hour): item
#             for item in oneDayData
#         }
#         print(hourly_data_map)

#         for leg_id in all_leg_ids:
#             aisle_name_obj = AisleGroup.objects.filter(virtual_siteID_id=site_id, attached_leg_id=leg_id).first()
#             name = aisle_name_obj.aisleGroupName if aisle_name_obj else leg_id
#             print("name is",name)
#             unitConsumptionList = []
#             savingConsumptionList = []

#             for i in range(24):
#                 unit_consumption = 0.0
#                 energy_saved = 0.0
#                 hourly_data = hourly_data_map.get((leg_id, i))

#                 if hourly_data:
#                     unit_consumption = hourly_data.unit_consumption
#                     energy_saved = hourly_data.energy_saved

#                 unitConsumptionList.append(round(unit_consumption, 2))
#                 savingConsumptionList.append(round(energy_saved, 2))

#             dataList.append({"name": name, "data": unitConsumptionList, "type": 'column'})
#             savingList.append({"name": name, "data": savingConsumptionList, 'type': 'column'})

#         if site.is_live:
#             latest_baseline = SiteBaseline.objects.filter(
#                                 aisle_group__virtual_siteID_id=site).exclude(Q(baseline_to__isnull=False)).aggregate(Sum('baseline_value'))['baseline_value__sum']
    
#             if datetime.now().date() == date.date() and latest_baseline is not None:
#                 baseline_list = [round(latest_baseline / 24, 2)] * 24
#             else:
#                 previous_baseline = DailySiteReading.objects.filter(
#                 aisle_group__virtual_siteID_id=site,
#                 reading_for=date.date()
#                 ).aggregate(Sum('daily_baseline_value'))['daily_baseline_value__sum']
        
#                 baseline_list = [round(previous_baseline / 24, 2)] * 24 if previous_baseline is not None else [0] * 24

#             dataList.append({"name": "baseline", "data": baseline_list, "type": "spline"})


#         end_time = datetime.now()
#         print("function end time is:", end_time)
#         time_taken = end_time - start_time
#         print("time_taken:", time_taken)

#         return Response({"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList})

class EnergySavingsHourlyBarChartVB(APIView):
    '''
    This API is used to get the hourly energy consumption data for a site on a given date. (For Savings Only)
    '''
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        site_id = data.get("site_id", "")
        start_time = datetime.now()
        print("function start time is:", start_time)

        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            return Response({"result": 0, "msg": "Site not found"}, status=404)

        date_str = data.get("date", "")
        try:
            date = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            return Response({"result": 0, "msg": "Invalid date format"}, status=400)


        hourList = ["{:02d}:00".format(i) for i in range(24)]
        dataList = []
        savingList = []

        from datetime import timedelta
        # Use exact date for reading_for
        target_date = date.date()
        
        all_leg_ids = list(DailySiteReading.objects.filter(
            aisle_group__virtual_siteID_id=site_id, reading_for=target_date
        ).values_list("leg_id", flat=True).distinct())

        start_of_day = date
        end_of_day = start_of_day + timedelta(days=1)

        # Optimize HourlySiteReading query with __gte and __lt instead of __date 
        # and remove select_related('aisle_group') to avoid slow joins
        oneDayData = HourlySiteReading.objects.filter(
            aisle_group__virtual_siteID_id=site_id, 
            reading_from__gte=start_of_day, 
            reading_from__lt=end_of_day, 
            is_visible=True
        ).values('leg_id', 'reading_from', 'unit_consumption', 'energy_saved')

        # Group by leg_id and hour to reduce the number of iterations
        hourly_data_map = {
            (item['leg_id'], item['reading_from'].hour): item
            for item in oneDayData
        }

        # Fetch AisleGroup names in a single query to eliminate N+1 issue
        aisle_map = dict(AisleGroup.objects.filter(
            virtual_siteID_id=site_id, attached_leg_id__in=all_leg_ids
        ).values_list('attached_leg_id', 'aisleGroupName'))

        for leg_id in all_leg_ids:
            name = aisle_map.get(leg_id, str(leg_id))
            
            unitConsumptionList = []
            savingConsumptionList = []

            for i in range(24):
                hourly_data = hourly_data_map.get((leg_id, i))
                
                if hourly_data:
                    unit_consumption = hourly_data['unit_consumption'] or 0.0
                    energy_saved = hourly_data['energy_saved'] or 0.0
                else:
                    unit_consumption = 0.0
                    energy_saved = 0.0

                unitConsumptionList.append(round(unit_consumption, 2))
                savingConsumptionList.append(round(energy_saved, 2))

            dataList.append({"name": name, "data": unitConsumptionList, "type": 'column'})
            savingList.append({"name": name, "data": savingConsumptionList, 'type': 'column'})

        if site.is_live:
            latest_baseline = SiteBaseline.objects.filter(
                                aisle_group__virtual_siteID_id=site_id).exclude(Q(baseline_to__isnull=False)).aggregate(Sum('baseline_value'))['baseline_value__sum']
    
            if datetime.now().date() == target_date and latest_baseline is not None:
                baseline_list = [round(latest_baseline / 24, 2)] * 24
            else:
                previous_baseline = DailySiteReading.objects.filter(
                    aisle_group__virtual_siteID_id=site_id,
                    reading_for=target_date
                ).aggregate(Sum('daily_baseline_value'))['daily_baseline_value__sum']
        
                baseline_list = [round(previous_baseline / 24, 2)] * 24 if previous_baseline is not None else [0] * 24

            dataList.append({"name": "baseline", "data": baseline_list, "type": "spline"})

        end_time = datetime.now()
        print("function end time is:", end_time)
        time_taken = end_time - start_time
        print("time_taken:", time_taken)

        return Response({"result": 1, "Hours": hourList, "Data": dataList, "SavingData": savingList})



class DownloadExcelVB(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data
            site_id = int(data.get("site_id"))
            user_type = int(data.get("user_type", ''))

            start_date = datetime.strptime(data.get("from_date"), "%Y-%m-%d")
            end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d")

            # Fetch aisles more efficiently
            if user_type == 1:
                aisles = AisleGroup.objects.filter(virtual_siteID_id=site_id)
            else:
                aisles = AisleGroup.objects.filter(virtual_siteID_id=site_id, is_visible=True)

            aisle_names = [aisle.aisleGroupName for aisle in aisles]
            leg_ids = [aisle.attached_leg_id for aisle in aisles]

            # Fetch all relevant readings in one query
            readings = DailySiteReading.objects.filter(
                aisle_group__virtual_siteID_id=site_id,
                leg_id__in=leg_ids,
                reading_for__range=[start_date, end_date]
            ).values('leg_id', 'reading_for').annotate(total_consumption=Sum('unit_consumption'))

            # Organize readings by date and leg_id
            readings_dict = defaultdict(lambda: defaultdict(float))
            for reading in readings:
                date = reading['reading_for'].strftime("%d-%b-%Y")
                readings_dict[date][reading['leg_id']] = round(reading['total_consumption'], 2)

            baseline_list = []

            # Baseline filtering
            latest_baseline_values = SiteBaseline.objects.filter(leg_id__in=leg_ids)
            print(latest_baseline_values)


            # Prepare data for DataFrame
            header = ["Date", "Baseline", "Savings", "TotalConsumption (KWH)"] + aisle_names
            data_rows = []

            for i in range((end_date - start_date).days + 1):
                current_date = (start_date + timedelta(days=i)).strftime("%d-%b-%Y")
                date = start_date + timedelta(days=i)
                baseline_value = latest_baseline_values.filter(baseline_from__lte=date).filter(Q(baseline_to__gte=date) | Q(baseline_to__isnull=True)).aggregate(Sum('baseline_value'))['baseline_value__sum'] or 0
                daily_readings = readings_dict.get(current_date, {})
                row = [current_date]
                total = 0
                for leg_id in leg_ids:
                    consumption = daily_readings.get(leg_id, 0)
                    total += consumption
                    row.append(consumption)
                row.insert(1, total)
                row.insert(1, round(baseline_value-total, 2))
                row.insert(1, round(baseline_value,2))
                data_rows.append(row)

            # Create CSV from DataFrame
            df = pd.DataFrame(data_rows, columns=header)
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename=output.csv'
            df.to_csv(response, index=False)

            return response

        except Exception as e:
            return Response({'message' : str(e)})


class ParticularSiteSnapshotEnergySavingApiVB(APIView):
    @entryExit
    def post(self, request):
        data = request.data
        # print("data of site snapshot", data)
        site_id = data.get("site_id", '')
        # print("site id is: ", site_id)
        site = Site.objects.get(id=site_id)
        carbon_visible = False
        carbon_emission_value = 0
        if site.is_carbon_emission_visible:
            carbon_emission_value = site.carbon_emission_value
            carbon_visible = True
        live_date = site.live_date
        # print("live_date :",live_date)
        user_type = data.get("user_type")
        # print("site data", site)
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        previous = datetime.strftime(previous_date, "%d-%b-%Y")
        if int(data.get("site_id", '')) == 34:
            baseline_date = datetime.now().replace(day=12, month=4, year=2023)
        else:
            baseline_date = site.baseline_date.date()
        date = datetime.strftime(baseline_date, "%d-%b-%Y")
        alarm = AlarmNotifications.objects.filter(site_id=site, user_level=4).count()
        # print("alarm count on site page: ", alarm)
        # daily = DailySiteReading.objects.filter(associated_Site=site)
        if site.live_date:
            # print("inside live date if condition: ")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(virtual_siteID=site_id, is_visible=True)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(aisle_group__virtual_siteID=site, leg_id__in=all_leg_id,
                                                        reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date,
                                                        is_visible=True)

            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(virtual_siteID=site_id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(aisle_group__virtual_siteID=site, leg_id__in=all_leg_id,
                                                        reading_for__gte=baseline_date,
                                                        reading_for__lte=previous_date, is_visible=True)
                live_date = site.live_date
                live_date = datetime.strftime(live_date, "%Y/%m/%d")

        else:
            # print("inside else condition. site is not live")
            if user_type == 1:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276,710])
                else:
                    aisle_group = AisleGroup.objects.filter(virtual_siteID=site_id, is_visible=True)
                # aisle_group = AisleGroup.objects.filter(site_id=site_id)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(aisle_group__virtual_siteID=site, reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, reading_for__lte=previous_date,
                                                        is_visible=True)
            else:
                if int(data.get("site_id", '')) == 34:
                    aisle_group = AisleGroup.objects.filter(attached_leg_id__in=[259, 260, 261, 276, 710])
                else:
                    aisle_group = AisleGroup.objects.filter(virtual_siteID=site_id, is_visible=True)
                all_leg_id = [aisle.attached_leg_id for aisle in aisle_group]
                daily = DailySiteReading.objects.filter(aisle_group__virtual_siteID=site, reading_for__lte=previous_date,
                                                        reading_for__gte=baseline_date,
                                                        leg_id__in=all_leg_id, )
                live_date = "Not Live yet"
        energyConsumed = 0.0
        energySaved = 0.0
        carbon_saved = 0.0

        for i in daily:
            # print("inside for loop!!!!")
            energyConsumed += i.unit_consumption
            # if i.energy_saved >= 0:
            energySaved += i.daily_baseline_value
        energySaved = energySaved - energyConsumed
        if carbon_visible:
            carbon_saved = energySaved * carbon_emission_value
        try:
            percentageSaved = str(round(energySaved * 100 / (energyConsumed + energySaved), 1)) + " %"
            # live_date = site.live_date
            # live_date = datetime.strftime(live_date, "%Y/%m/%d")
        except Exception as e:
            print("exception is", e)
            percentageSaved = str(0.0) + " %"
        return Response({"result": 1, "alarms": alarm,
                         "energy_consumed": str(round(energyConsumed, 1)),
                         "saved_energy": str(round(energySaved, 1)),
                         "carbon_emission_saved": str(round(carbon_saved, 1)),
                         "percentage_saved": percentageSaved,
                         "live_date": date, "previous_date": previous,"site_live_date":live_date})


class SiteConsumptionPingApi(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @entryExit
    def post(self, request):
        try:
            data = request.data
            user_id = data.get("id", "")
            site_id = data.get("siteId", "")
            
            pings = SiteConsumptionPing.objects.all()
            
            if site_id:
                pings = pings.filter(site_id=site_id)
            elif user_id:
                try:
                    customer = User.objects.get(id=int(user_id))
                    if customer.UserType == 5:
                        user_sites = CustomerSiteManager.objects.get(customer=customer).associated_site.all()
                    else:
                        user_sites = Site.objects.filter(customer=customer)
                    pings = pings.filter(site__in=user_sites)
                except Exception as e:
                    pass
            
            response_data = []
            for p in pings:
                response_data.append({
                    "site_id": p.site.id if p.site else None,
                    "site_name": p.site.site_name if p.site else None,
                    "home_gateway_id": p.home_gateway_id,
                    "consumption_ping_time": p.consumption_ping_time.strftime("%Y-%m-%d %H:%M:%S") if p.consumption_ping_time else None,
                    "updated_on": p.updated_on.strftime("%Y-%m-%d %H:%M:%S") if p.updated_on else None,
                })
                
            return Response({"result": 1, "data": response_data})
        except Exception as err:
            return Response({"result": 0, "msg": str(err)})


class SiteCeleryPingApi(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @entryExit
    def post(self, request):
        try:
            data = request.data
            user_id = data.get("id", "")
            site_id = data.get("siteId", "")

            pings = SiteCeleryPing.objects.all()

            if site_id:
                pings = pings.filter(site_id=site_id)
            elif user_id:
                try:
                    customer = User.objects.get(id=int(user_id))
                    if customer.UserType == 5:
                        user_sites = CustomerSiteManager.objects.get(customer=customer).associated_site.all()
                    else:
                        user_sites = Site.objects.filter(customer=customer)
                    pings = pings.filter(site__in=user_sites)
                except Exception as e:
                    pass

            response_data = []
            for p in pings:
                response_data.append({
                    "site_id": p.site.id if p.site else None,
                    "site_name": p.site.site_name if p.site else None,
                    "home_gateway_id": p.home_gateway_id,
                    "leg_id": p.leg_id,
                    "aisle_group": p.aisle_group,
                    "unit_consumption": p.unit_consumption,
                    "celery_ping_time": p.celery_ping_time.strftime("%Y-%m-%d %H:%M:%S") if p.celery_ping_time else None,
                    "updated_on": p.updated_on.strftime("%Y-%m-%d %H:%M:%S") if p.updated_on else None,
                })

            response_data.sort(key=lambda x: 0 if x.get("unit_consumption") == 0.0 else 1)
            return Response({"result": 1, "data": response_data})
        except Exception as err:
            return Response({"result": 0, "msg": str(err)})


def test_function(request):
    return HttpResponse({"msg":"things are working fine!!"})


class SiteAisleGroupsWithLastEntries(APIView):
    permission_classes = [AllowAny]

    def _serialize_hourly_entry(self, hourly_entry):
        if not hourly_entry:
            return None

        return {
            "id": hourly_entry.id,
            "unit_consumption": hourly_entry.unit_consumption,
            "energy_saved": hourly_entry.energy_saved,
            "reading_from": hourly_entry.reading_from,
            "reading_to": hourly_entry.reading_to,
        }

    def _serialize_daily_entry(self, daily_entry):
        if not daily_entry:
            return None

        return {
            "id": daily_entry.id,
            "unit_consumption": daily_entry.unit_consumption,
            "energy_saved": daily_entry.energy_saved,
            "reading_for": daily_entry.reading_for,
        }

    def _get_latest_hourly_entries(self, site_ids, leg_ids, required_keys):
        latest_entries = {}
        hourly_entries = HourlySiteReading.objects.filter(
            associated_Site_id__in=site_ids,
            leg_id__in=leg_ids
        ).values(
            'id',
            'associated_Site_id',
            'leg_id',
            'unit_consumption',
            'energy_saved',
            'reading_from',
            'reading_to'
        ).order_by('associated_Site_id', 'leg_id', '-reading_from', '-id')

        for entry in hourly_entries.iterator(chunk_size=2000):
            entry_key = (entry['associated_Site_id'], entry['leg_id'])
            if entry_key in required_keys and entry_key not in latest_entries:
                latest_entries[entry_key] = {
                    "id": entry['id'],
                    "unit_consumption": entry['unit_consumption'],
                    "energy_saved": entry['energy_saved'],
                    "reading_from": entry['reading_from'],
                    "reading_to": entry['reading_to'],
                }
                if len(latest_entries) == len(required_keys):
                    break

        return latest_entries

    def _get_latest_daily_entries(self, site_ids, leg_ids, required_keys):
        latest_entries = {}
        daily_entries = DailySiteReading.objects.filter(
            associated_Site_id__in=site_ids,
            leg_id__in=leg_ids
        ).values(
            'id',
            'associated_Site_id',
            'leg_id',
            'unit_consumption',
            'energy_saved',
            'reading_for'
        ).order_by('associated_Site_id', 'leg_id', '-reading_for', '-id')

        for entry in daily_entries.iterator(chunk_size=2000):
            entry_key = (entry['associated_Site_id'], entry['leg_id'])
            if entry_key in required_keys and entry_key not in latest_entries:
                latest_entries[entry_key] = {
                    "id": entry['id'],
                    "unit_consumption": entry['unit_consumption'],
                    "energy_saved": entry['energy_saved'],
                    "reading_for": entry['reading_for'],
                }
                if len(latest_entries) == len(required_keys):
                    break

        return latest_entries

    def _build_response(self, request):
        site_id = request.data.get("site_id") if request.method == "POST" else request.query_params.get("site_id")

        sites = Site.objects.all().order_by('id')
        if site_id:
            sites = sites.filter(id=site_id)

        sites = list(sites)
        if not sites:
            return Response({"result": 1, "data": []}, status=status.HTTP_200_OK)

        site_ids = [site.id for site in sites]
        aisle_groups = list(AisleGroup.objects.filter(site_id__in=site_ids).order_by('site_id', 'id'))

        site_wise_aisles = defaultdict(list)
        required_keys = set()
        leg_ids = set()
        for aisle_group in aisle_groups:
            site_wise_aisles[aisle_group.site_id].append(aisle_group)
            entry_key = (aisle_group.site_id, aisle_group.attached_leg_id)
            required_keys.add(entry_key)
            if aisle_group.attached_leg_id:
                leg_ids.add(aisle_group.attached_leg_id)

        latest_hourly_entries = {}
        latest_daily_entries = {}
        if required_keys and leg_ids:
            latest_hourly_entries = self._get_latest_hourly_entries(site_ids, leg_ids, required_keys)
            latest_daily_entries = self._get_latest_daily_entries(site_ids, leg_ids, required_keys)

        response_data = []
        for site in sites:
            aisle_groups_data = []
            for aisle_group in site_wise_aisles.get(site.id, []):
                entry_key = (site.id, aisle_group.attached_leg_id)
                latest_hourly_entry = latest_hourly_entries.get(entry_key)
                latest_daily_entry = latest_daily_entries.get(entry_key)

                aisle_groups_data.append({
                    "aisle_group_id": aisle_group.id,
                    "aisle_group_name": aisle_group.aisleGroupName,
                    "attached_leg_id": aisle_group.attached_leg_id,
                    "is_visible": aisle_group.is_visible,
                    "is_active": aisle_group.is_active,
                    "last_hourly_entry": latest_hourly_entry,
                    "last_daily_entry": latest_daily_entry,
                })

            response_data.append({
                "site_id": site.id,
                "site_name": site.site_name,
                "site_type": site.site_type,
                "customer_id": site.customer_id,
                "is_live": site.is_live,
                "is_visible": site.is_visible,
                "aisle_groups": aisle_groups_data,
            })

        return Response({"result": 1, "data": response_data}, status=status.HTTP_200_OK)

    @entryExit
    def get(self, request):
        return self._build_response(request)

    @entryExit
    def post(self, request):
        return self._build_response(request)

