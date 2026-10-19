"""Site/gateway health: pings, gateway status, meter disconnections."""

from collections import defaultdict

from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import (
    AisleGroup,
    CustomerSiteManager,
    DailySiteReading,
    HomeGatewayId,
    HomeGatewayStatus,
    HourlySiteReading,
    MeterDisconnectionEvent,
    Site,
    SiteCeleryPing,
    SiteConsumptionPing,
    User,
)
from wareApp.serializers import MeterDisconnectionEventSerializer
from wareApp.utility import entryExit


class SiteConsumptionPingApi(APIView):
    permission_classes = [AllowAny]

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
                        user_sites = CustomerSiteManager.objects.get(
                            customer=customer
                        ).associated_site.all()
                    else:
                        user_sites = Site.objects.filter(customer=customer)
                    pings = pings.filter(site__in=user_sites)
                except Exception as e:
                    pass

            response_data = []
            for p in pings:
                response_data.append(
                    {
                        "site_id": p.site.id if p.site else None,
                        "site_name": p.site.site_name if p.site else None,
                        "home_gateway_id": p.home_gateway_id,
                        "consumption_ping_time": (
                            p.consumption_ping_time.strftime("%Y-%m-%d %H:%M:%S")
                            if p.consumption_ping_time
                            else None
                        ),
                        "updated_on": (
                            p.updated_on.strftime("%Y-%m-%d %H:%M:%S")
                            if p.updated_on
                            else None
                        ),
                    }
                )

            response_data.sort(
                key=lambda x: 0 if x.get("unit_consumption") == 0.0 else 1
            )
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

            # pagination params
            try:
                page = int(data.get("page", 1))
            except Exception:
                page = 1
            try:
                page_size = int(data.get("page_size", 50))
            except Exception:
                page_size = 50
            if page < 1:
                page = 1
            if page_size < 1:
                page_size = 50
            if page_size > 500:
                page_size = 500

            qs = SiteCeleryPing.objects.all()

            if site_id:
                qs = qs.filter(site_id=site_id)
            elif user_id:
                try:
                    customer = User.objects.get(id=int(user_id))
                    if customer.UserType == 5:
                        user_sites = CustomerSiteManager.objects.get(
                            customer=customer
                        ).associated_site.all()
                    else:
                        user_sites = Site.objects.filter(customer=customer)
                    qs = qs.filter(site__in=user_sites)
                except Exception:
                    pass

            # Optimize: annotate a sort key for zero consumption and let DB do ordering.
            from django.db.models import Case, IntegerField, When

            qs = (
                qs.select_related("site")
                .annotate(
                    zero_consumption=Case(
                        When(unit_consumption__exact=0, then=0),
                        default=1,
                        output_field=IntegerField(),
                    )
                )
                .order_by("zero_consumption", "-celery_ping_time")
            )

            total = qs.count()

            start = (page - 1) * page_size
            end = start + page_size

            # Use values() to fetch only required fields and avoid model instantiation overhead
            page_qs = qs.values(
                "site_id",
                "site__site_name",
                "home_gateway_id",
                "leg_id",
                "aisle_group",
                "unit_consumption",
                "celery_ping_time",
                "updated_on",
            )[start:end]

            response_data = []
            for p in page_qs:
                celery_ping_time = p.get("celery_ping_time")
                updated_on = p.get("updated_on")
                response_data.append(
                    {
                        "site_id": p.get("site_id"),
                        "site_name": p.get("site__site_name"),
                        "home_gateway_id": p.get("home_gateway_id"),
                        "leg_id": p.get("leg_id"),
                        "aisle_group": p.get("aisle_group"),
                        "unit_consumption": p.get("unit_consumption"),
                        "celery_ping_time": (
                            celery_ping_time.strftime("%Y-%m-%d %H:%M:%S")
                            if celery_ping_time
                            else None
                        ),
                        "updated_on": (
                            updated_on.strftime("%Y-%m-%d %H:%M:%S")
                            if updated_on
                            else None
                        ),
                    }
                )

            return Response(
                {
                    "result": 1,
                    "data": response_data,
                    "pagination": {
                        "total": total,
                        "page": page,
                        "page_size": page_size,
                    },
                }
            )
        except Exception as err:
            return Response({"result": 0, "msg": str(err)})


class SiteAisleGroupsWithLastEntries(APIView):
    permission_classes = [AllowAny]

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
        hourly_entries = (
            HourlySiteReading.objects.filter(
                associated_Site_id__in=site_ids, leg_id__in=leg_ids
            )
            .values(
                "id",
                "associated_Site_id",
                "leg_id",
                "unit_consumption",
                "energy_saved",
                "reading_from",
                "reading_to",
            )
            .order_by("associated_Site_id", "leg_id", "-reading_from", "-id")
        )

        for entry in hourly_entries.iterator(chunk_size=2000):
            entry_key = (entry["associated_Site_id"], entry["leg_id"])
            if entry_key in required_keys and entry_key not in latest_entries:
                latest_entries[entry_key] = {
                    "id": entry["id"],
                    "unit_consumption": entry["unit_consumption"],
                    "energy_saved": entry["energy_saved"],
                    "reading_from": entry["reading_from"],
                    "reading_to": entry["reading_to"],
                }
                if len(latest_entries) == len(required_keys):
                    break

        return latest_entries

    def _get_latest_daily_entries(self, site_ids, leg_ids, required_keys):
        latest_entries = {}
        daily_entries = (
            DailySiteReading.objects.filter(
                associated_Site_id__in=site_ids, leg_id__in=leg_ids
            )
            .values(
                "id",
                "associated_Site_id",
                "leg_id",
                "unit_consumption",
                "energy_saved",
                "reading_for",
            )
            .order_by("associated_Site_id", "leg_id", "-reading_for", "-id")
        )

        for entry in daily_entries.iterator(chunk_size=2000):
            entry_key = (entry["associated_Site_id"], entry["leg_id"])
            if entry_key in required_keys and entry_key not in latest_entries:
                latest_entries[entry_key] = {
                    "id": entry["id"],
                    "unit_consumption": entry["unit_consumption"],
                    "energy_saved": entry["energy_saved"],
                    "reading_for": entry["reading_for"],
                }
                if len(latest_entries) == len(required_keys):
                    break

        return latest_entries

    def _build_response(self, request):
        site_id = (
            request.data.get("site_id")
            if request.method == "POST"
            else request.query_params.get("site_id")
        )

        sites = Site.objects.all().order_by("id")
        if site_id:
            sites = sites.filter(id=site_id)

        sites = list(sites)
        if not sites:
            return Response({"result": 1, "data": []}, status=status.HTTP_200_OK)

        site_ids = [site.id for site in sites]
        aisle_groups = list(
            AisleGroup.objects.filter(site_id__in=site_ids).order_by("site_id", "id")
        )

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
            latest_hourly_entries = self._get_latest_hourly_entries(
                site_ids, leg_ids, required_keys
            )
            latest_daily_entries = self._get_latest_daily_entries(
                site_ids, leg_ids, required_keys
            )

        response_data = []
        for site in sites:
            aisle_groups_data = []
            for aisle_group in site_wise_aisles.get(site.id, []):
                entry_key = (site.id, aisle_group.attached_leg_id)
                latest_hourly_entry = latest_hourly_entries.get(entry_key)
                latest_daily_entry = latest_daily_entries.get(entry_key)

                aisle_groups_data.append(
                    {
                        "aisle_group_id": aisle_group.id,
                        "aisle_group_name": aisle_group.aisleGroupName,
                        "attached_leg_id": aisle_group.attached_leg_id,
                        "is_visible": aisle_group.is_visible,
                        "is_active": aisle_group.is_active,
                        "last_hourly_entry": latest_hourly_entry,
                        "last_daily_entry": latest_daily_entry,
                    }
                )

            response_data.append(
                {
                    "site_id": site.id,
                    "site_name": site.site_name,
                    "site_type": site.site_type,
                    "customer_id": site.customer_id,
                    "is_live": site.is_live,
                    "is_visible": site.is_visible,
                    "aisle_groups": aisle_groups_data,
                }
            )

        return Response({"result": 1, "data": response_data}, status=status.HTTP_200_OK)

    @entryExit
    def get(self, request):
        return self._build_response(request)

    @entryExit
    def post(self, request):
        return self._build_response(request)


class MeterDisconnectionIngestView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.data
        if isinstance(payload, dict):
            payload = [payload]

        if not isinstance(payload, list):
            return Response(
                {"status": 400, "msg": "Payload must be object or list."}, status=400
            )

        saved = 0

        for entry in payload:
            meter_id = entry.get("meter_id")
            if not meter_id:
                continue

            defaults = {
                "remote_site_id": entry.get("site"),
                "logged_site_id": entry.get("logged_site_id"),
                "meter_source_id": entry.get("meter_source"),
                "meter_number": entry.get("meter_number"),
                "meter_name": entry.get("meter_name") or "meter{}".format(meter_id),
                "status": entry.get("status") or "disconnected",
                "port_id": entry.get("port_id"),
                "detection_window_start": (
                    parse_datetime(entry.get("detection_window_start") or "")
                    if entry.get("detection_window_start")
                    else None
                ),
                "detection_window_end": (
                    parse_datetime(entry.get("detection_window_end") or "")
                    if entry.get("detection_window_end")
                    else None
                ),
                "last_seen_at": (
                    parse_datetime(entry.get("last_seen_at") or "")
                    if entry.get("last_seen_at")
                    else None
                ),
                "source_log_path": entry.get("source_log_path") or "",
                "raw_log_line": entry.get("raw_log_line"),
                "synced_to_cloud": True,
                "synced_at": (
                    parse_datetime(entry.get("synced_at") or "")
                    if entry.get("synced_at")
                    else None
                ),
                "cloud_response": entry.get("cloud_response"),
            }

            # Self-healing: Clean up duplicate records if they exist in the DB
            existing_events = list(
                MeterDisconnectionEvent.objects.filter(meter_id=meter_id).order_by(
                    "-updated_at"
                )
            )
            if len(existing_events) > 1:
                existing_event = existing_events[0]
                for key, val in defaults.items():
                    setattr(existing_event, key, val)
                existing_event.save()
                for dup in existing_events[1:]:
                    dup.delete()
                created = False
            elif len(existing_events) == 1:
                existing_event = existing_events[0]
                for key, val in defaults.items():
                    setattr(existing_event, key, val)
                existing_event.save()
                created = False
            else:
                MeterDisconnectionEvent.objects.create(meter_id=meter_id, **defaults)
                created = True

            if created:
                saved += 1

        return Response({"status": 200, "saved": saved, "received": len(payload)})


class MeterDisconnectionListView(APIView):
    def get(self, request):
        queryset = MeterDisconnectionEvent.objects.all().order_by(
            "-updated_at", "meter_number", "meter_id"
        )

        logged_site_id = request.query_params.get(
            "logged_site_id"
        ) or request.query_params.get("site_id")
        meter_number = request.query_params.get("meter_number")
        meter_id = request.query_params.get("meter_id")
        status_value = request.query_params.get("status")
        from_date = request.query_params.get("from")
        to_date = request.query_params.get("to")

        if logged_site_id:
            queryset = queryset.filter(logged_site_id=logged_site_id)
        if meter_number:
            queryset = queryset.filter(meter_number=meter_number)
        if meter_id:
            queryset = queryset.filter(meter_id=meter_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        if from_date:
            parsed_from = parse_datetime(from_date)
            if parsed_from:
                queryset = queryset.filter(updated_at__gte=parsed_from)
        if to_date:
            parsed_to = parse_datetime(to_date)
            if parsed_to:
                queryset = queryset.filter(updated_at__lte=parsed_to)

        total = queryset.count()
        try:
            limit = int(request.query_params.get("limit", 100))
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            return Response(
                {"status": 400, "msg": "limit and offset must be numbers."}, status=400
            )

        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        serializer = MeterDisconnectionEventSerializer(
            queryset[offset : offset + limit], many=True
        )

        return Response(
            {
                "status": 200,
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": serializer.data,
            }
        )


class HomeGatewayStatusApi(APIView):
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        try:
            queryset = (
                HomeGatewayStatus.objects.select_related(
                    "home_gateway",
                    "home_gateway__connected_to",
                    "home_gateway__connected_to__customer",
                    "home_gateway__owned_by__customer",
                )
                .all()
                .order_by("id")
            )

            total = queryset.count()

            try:
                limit = int(request.query_params.get("limit", 100))
                offset = int(request.query_params.get("offset", 0))
            except ValueError:
                return Response(
                    {"status": 400, "message": "limit and offset must be integers."},
                    status=400,
                )

            limit = max(1, min(limit, 500))
            offset = max(0, offset)

            gateways = queryset[offset : offset + limit]

            data = []
            for gw in gateways:
                hgw = gw.home_gateway
                site = hgw.connected_to if hgw else None
                customer_name = "N/A"
                if hgw:
                    if hgw.owned_by and hgw.owned_by.customer:
                        customer_name = hgw.owned_by.customer.username
                    elif site and site.customer:
                        customer_name = site.customer.username

                data.append(
                    {
                        "id": gw.id,
                        "gateway_id": hgw.hgw_id if hgw else None,
                        "latitude": (
                            float(gw.latitude) if gw.latitude is not None else None
                        ),
                        "longitude": (
                            float(gw.longitude) if gw.longitude is not None else None
                        ),
                        "status": gw.status,
                        "site_id": site.id if site else None,
                        "site_name": site.site_name if site else "N/A",
                        "customer_name": customer_name,
                    }
                )

            return Response(
                {
                    "status": 200,
                    "count": total,
                    "limit": limit,
                    "offset": offset,
                    "results": data,
                }
            )
        except Exception as err:
            return Response(
                {"status": 500, "message": "Internal Server Error", "error": str(err)},
                status=500,
            )

    def post(self, request):
        try:
            gateway_id = request.data.get("gateway_id")
            status_id = request.data.get("id")

            if not gateway_id and not status_id:
                return Response(
                    {
                        "status": 400,
                        "message": "Either 'gateway_id' or 'id' must be provided.",
                    },
                    status=400,
                )

            # Find or create the HomeGatewayStatus object
            if status_id:
                try:
                    obj = HomeGatewayStatus.objects.get(id=status_id)
                except HomeGatewayStatus.DoesNotExist:
                    return Response(
                        {
                            "status": 404,
                            "message": f"HomeGatewayStatus with id {status_id} not found.",
                        },
                        status=404,
                    )
            else:
                try:
                    obj = HomeGatewayStatus.objects.get(home_gateway__hgw_id=gateway_id)
                except HomeGatewayStatus.DoesNotExist:
                    # Try to create it if HomeGatewayId exists
                    try:
                        hgw_obj = HomeGatewayId.objects.get(hgw_id=gateway_id)
                        obj = HomeGatewayStatus.objects.create(home_gateway=hgw_obj)
                    except HomeGatewayId.DoesNotExist:
                        return Response(
                            {
                                "status": 404,
                                "message": f"HomeGatewayId with hgw_id {gateway_id} not found.",
                            },
                            status=404,
                        )

            # Update fields if provided in request body
            if "latitude" in request.data:
                lat = request.data.get("latitude")
                if lat is not None and lat != "":
                    try:
                        from decimal import Decimal

                        obj.latitude = Decimal(str(lat))
                    except (ValueError, TypeError, ArithmeticError):
                        return Response(
                            {"status": 400, "message": "Invalid latitude format."},
                            status=400,
                        )
                else:
                    obj.latitude = None

            if "longitude" in request.data:
                lon = request.data.get("longitude")
                if lon is not None and lon != "":
                    try:
                        from decimal import Decimal

                        obj.longitude = Decimal(str(lon))
                    except (ValueError, TypeError, ArithmeticError):
                        return Response(
                            {"status": 400, "message": "Invalid longitude format."},
                            status=400,
                        )
                else:
                    obj.longitude = None

            if "status" in request.data:
                status_val = request.data.get("status")
                if isinstance(status_val, str):
                    obj.status = status_val.lower() in ("true", "1", "yes")
                else:
                    obj.status = bool(status_val)

            obj.save()

            hgw = obj.home_gateway
            site = hgw.connected_to if hgw else None
            customer_name = "N/A"
            if hgw:
                if hgw.owned_by and hgw.owned_by.customer:
                    customer_name = hgw.owned_by.customer.username
                elif site and site.customer:
                    customer_name = site.customer.username

            return Response(
                {
                    "status": 200,
                    "message": "Gateway status updated successfully.",
                    "data": {
                        "id": obj.id,
                        "gateway_id": hgw.hgw_id if hgw else None,
                        "latitude": (
                            float(obj.latitude) if obj.latitude is not None else None
                        ),
                        "longitude": (
                            float(obj.longitude) if obj.longitude is not None else None
                        ),
                        "status": obj.status,
                        "site_id": site.id if site else None,
                        "site_name": site.site_name if site else "N/A",
                        "customer_name": customer_name,
                    },
                }
            )
        except Exception as err:
            return Response(
                {"status": 500, "message": "Internal Server Error", "error": str(err)},
                status=500,
            )
