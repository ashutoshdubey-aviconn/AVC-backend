"""Provisioning-script endpoints (customers, sites, aisle groups, gateways)."""

from datetime import datetime

from django.contrib.auth.hashers import make_password
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp.models import AisleGroup, CustomerInfo, HomeGatewayId, Site, User
from wareApp.utility import entryExit, logger


class FetchAllCustomers(APIView):
    """API view for /api/fetchAllCustomers/ (GET; Open: no login (AllowAny)). Reads User. Returns data,
    msg, status.

    Origin: main (unchanged)
    """
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request):
        """GET /api/fetchAllCustomers/. No request fields. Response keys: data, msg, status.

        Origin: main (unchanged)
        """
        header = request.META.get("HTTP_AUTHORIZATION")
        customers = User.objects.filter(UserType=4)
        customer_data_list = []
        if customers.exists():
            for i in customers:
                customer_data_list.append(
                    {"id": i.id, "username": i.username, "email": i.email}
                )
        return Response(
            {"status": 200, "msg": "customer details", "data": customer_data_list}
        )


class CreateCustomerUsingProvisioning(APIView):
    """API view for /api/createCustomer/ (POST; Open: no login (AllowAny)). Saves to CustomerInfo,
    User. Takes customer_contact, customer_email, customer_name. Returns error, msg, status,
    user_id.

    Origin: Ashu (changed from main)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/createCustomer/. Request fields: customer_contact, customer_email, customer_name.
        Response keys: error, msg, status, user_id.

        Origin: Ashu (changed from main)
        """
        data = request.data
        try:
            username = data.get("customer_name")
            password = "Aviconn@123#"
            customer_type = 4
            email = data.get("customer_email")
            contact = data.get("customer_contact")
            currentdate = datetime.now()
            user = User.objects.create(
                username=username,
                password=make_password(password),
                email=email,
                Contact_number=contact,
                UserType=customer_type,
            )

            if user:
                customer = CustomerInfo.objects.create(customer=user)
                return Response(
                    {"status": 200, "msg": "user created", "user_id": user.id}
                )
            return Response({"status": 400, "msg": "unable to create user"})
        except Exception as err:
            logger.debug("%s %s", "error", err)
            return Response(
                {"status": 500, "msg": "server error", "error": err.__class__.__name__}
            )


class CreateSiteUsingProvisioning(APIView):
    """API view for /api/createSite/ (POST; Open: no login (AllowAny)). Saves to Site. Reads User.
    Takes customer_id, site_location, site_name, site_type. Returns msg, site_id, status.

    Origin: main (unchanged)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/createSite/. Request fields: customer_id, site_location, site_name, site_type.
        Response keys: msg, site_id, status.

        Origin: main (unchanged)
        """
        data = request.data
        sitename = data.get("site_name")
        sitetype = data.get("site_type")
        location = data.get("site_location")
        customer_id = data.get("customer_id")
        customer = User.objects.get(id=customer_id)
        site = Site.objects.create(
            customer=customer,
            site_name=sitename,
            site_type=sitetype,
            location=location,
            live_date=datetime.now(),
        )

        if site:
            return Response(
                {"status": 200, "msg": "site created successfully", "site_id": site.id}
            )
        return Response({"status": 500, "msg": "unable to create site"})


class FetchAllSitesForProvisoning(APIView):
    """API view for /api/allSitesList/ (GET; Open: no login (AllowAny)). Reads Site. Returns data,
    status.

    Origin: Ashu (changed from main)
    """
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request):
        """GET /api/allSitesList/. No request fields. Response keys: data, status.

        Origin: Ashu (changed from main)
        """
        all_sites = Site.objects.all()
        site_list = []
        for i in all_sites:
            site_list.append(
                {
                    "id": i.id,
                    "site_name": i.site_name,
                    "location": i.location,
                    "site_type": i.site_type,
                    "customer_id": i.customer_id,  # Add this line
                }
            )
        return Response({"status": 200, "data": site_list})


class CreateAisleGroupUsingProvisioning(APIView):
    """API view for /api/createAisleGroups/ (POST; Open: no login (AllowAny)). Saves to AisleGroup.
    Reads Site. Takes aisle_name, power_source, site_id, site_type. Returns aisle_id, error, msg,
    status.

    Origin: main (unchanged)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/createAisleGroups/. Request fields: aisle_name, power_source, site_id, site_type.
        Response keys: aisle_id, error, msg, status.

        Origin: main (unchanged)
        """
        try:
            data = request.data
            aisle_name = data.get("aisle_name")
            site_id = data.get("site_id")
            site_type = data.get("site_type")
            site = Site.objects.get(id=site_id)
            if site_type == 1:
                power_source = data.get("power_source")
                aisle_group = AisleGroup.objects.create(
                    site=site,
                    aisleGroupName=aisle_name,
                    is_this_power_source=True,
                    power_source=power_source,
                )
            else:
                aisle_group = AisleGroup.objects.create(
                    site=site, aisleGroupName=aisle_name
                )
            return Response(
                {
                    "status": 200,
                    "msg": "aisle group created successfully",
                    "aisle_id": aisle_group.id,
                }
            )
        except Exception as err:
            return Response(
                {
                    "status": 500,
                    "msg": "internal server error",
                    "error": err.__class__.__name__,
                }
            )


class CreateHomeGatewayIdUsingProvisioning(APIView):
    """API view for /api/createHomeGatewayId/ (POST; Open: no login (AllowAny)). Saves to
    HomeGatewayId. Reads Site. Takes home_gateway_name, monitoring_port, rssh_port, site_id. Returns
    error, msg, status.

    Origin: Ashu (changed from main)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/createHomeGatewayId/. Request fields: home_gateway_name, monitoring_port,
        rssh_port, site_id. Response keys: error, msg, status.

        Origin: Ashu (changed from main)
        """
        try:
            data = request.data
            logger.debug("%s %s", "data : ", data)
            home_gateway_name = data.get("home_gateway_name")
            rssh_port = data.get("rssh_port")
            monitoring_port = data.get("monitoring_port")
            site_id = data.get("site_id")
            site = Site.objects.get(id=site_id)
            homeGateway = HomeGatewayId.objects.create(
                connected_to=site,
                hgw_id=home_gateway_name,
                rssh_port=rssh_port,
                monitoring_port=monitoring_port,
            )
            logger.debug("%s %s", "homeGateway", homeGateway)
            if homeGateway:
                return Response(
                    {"status": 200, "msg": "home gateway id created successfully"}
                )
        except Exception as err:
            logger.debug("%s %s", "error : ", err)
            return Response(
                {
                    "status": 500,
                    "msg": "internal server error",
                    "error": err.__class__.__name__,
                }
            )


class FetchAisleGroupsForParticularSiteUsingProvisioning(APIView):
    """API view for /api/fetchAisleGroups/ (POST; Open: no login (AllowAny)). Reads AisleGroup. Takes
    site_id. Returns data, error, status.

    Origin: Ashu (changed from main)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/fetchAisleGroups/. Request fields: site_id. Response keys: data, error, status.

        Origin: Ashu (changed from main)
        """
        try:
            data = request.data
            site_id = data.get("site_id")
            aisle_groups = AisleGroup.objects.filter(site_id=site_id).values()
            return Response({"status": 200, "data": list(aisle_groups)})
        except Exception as err:
            return Response({"status": 500, "error": err.__class__.__name__})


class FetchHGID(APIView):
    """API view for /api/fetchHomeGatewayId/ (GET; Open: no login (AllowAny)). Reads HomeGatewayId.
    Takes site_id. Returns msg, status.

    Origin: Ashu
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """GET /api/fetchHomeGatewayId/. Request fields: site_id. Response keys: msg, status.

        Origin: Ashu
        """
        try:
            site_id = request.query_params.get("site_id")

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
    """API view for /api/fetchParticularCustomer/ (POST; Open: no login (AllowAny)). Reads User. Takes
    id. Returns contact, email, status, username.

    Origin: main (unchanged)
    """
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        """POST /api/fetchParticularCustomer/. Request fields: id. Response keys: contact, email,
        status, username.

        Origin: main (unchanged)
        """
        data = request.data
        customer_id = data.get("id", "")
        customer = User.objects.get(id=customer_id)
        return Response(
            {
                "status": 200,
                "username": customer.username,
                "email": customer.email,
                "contact": customer.Contact_number,
            }
        )


class FetchLastRsshPort(APIView):
    """API view for /api/fetchLastRsshPort/ (GET; Open: no login (AllowAny)). Reads HomeGatewayId.
    Returns rssh_port, status.

    Origin: main (unchanged)
    """
    permission_classes = [AllowAny]

    @entryExit
    def get(self, request):
        """GET /api/fetchLastRsshPort/. No request fields. Response keys: rssh_port, status.

        Origin: main (unchanged)
        """
        rssh_port = HomeGatewayId.objects.all().order_by("-id")[0]
        return Response({"status": 200, "rssh_port": rssh_port.rssh_port})
