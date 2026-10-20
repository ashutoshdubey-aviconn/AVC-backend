"""Receiver for the gateways' overheat alerts (see wareApp/gateway_overheat.py)."""

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from wareApp.gateway_overheat import InvalidOverheatAlert, parse_alert, record_overheat
from wareApp.models import Site

logger = logging.getLogger(__name__)

__all__ = ["GatewayOverheatAlertApi"]


class GatewayOverheatThrottle(AnonRateThrottle):
    """Gateways post every few seconds while hot; allow that, cap anything more."""

    scope = "gateway_overheat"


class GatewayOverheatAlertApi(APIView):
    # Called by the gateway script, which has no account or token.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [GatewayOverheatThrottle]

    def post(self, request):
        try:
            alert = parse_alert(request.data)
            outcome = record_overheat(alert)
        except InvalidOverheatAlert as error:
            return Response({"status": "rejected", "error": str(error)},
                            status=status.HTTP_400_BAD_REQUEST)
        except Site.DoesNotExist:
            return Response({"status": "rejected", "error": "unknown site"},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": outcome})
