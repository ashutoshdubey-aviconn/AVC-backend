import logging

from rest_framework.views import APIView
from rest_framework.response import Response

from wareApp.models import Site
from .processor import process_http_recovery

logger = logging.getLogger(__name__)


class RecoveryUploadAPIView(APIView):

    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    def post(self, request):
        recovery_payload = request.data.get("Recovery Payload")

        if not recovery_payload:
            logger.warning(
                "Recovery upload rejected reason=missing_payload request_keys=%s",
                sorted(request.data.keys()),
            )
            return Response(
                {
                    "status": False,
                    "message": "Recovery Payload missing",
                },
                status=400,
            )

        try:
            topic = recovery_payload[0]
            location_id = int(recovery_payload[1])
            gateway_id = recovery_payload[2]
            recovery_data = recovery_payload[3]
            # gw_total_cumulative = recovery_payload[4]
            head = topic.split("/")
            msg_type = head[6]
            msg_subtype = head[7]
        except (IndexError, TypeError, ValueError) as exc:
            logger.warning(
                "Recovery upload rejected reason=invalid_payload error=%s", exc
            )
            return Response(
                {
                    "status": False,
                    "message": str(exc),
                },
                status=400,
            )

        logger.info(
            "Recovery upload accepted site_id=%s gateway_id=%s type=%s subtype=%s topic=%s",
            location_id,
            gateway_id,
            msg_type,
            msg_subtype,
            topic,
        )

        try:
            site = Site.objects.get(id=location_id)
        except Site.DoesNotExist:
            logger.warning(
                "Recovery upload rejected reason=invalid_site site_id=%s", location_id
            )
            return Response({"status": False, "message": "Invalid Site"}, status=404)

        result = process_http_recovery(
            site=site,
            gateway_id=gateway_id,
            location_id=location_id,
            msg_type=msg_type,
            msg_subtype=msg_subtype,
            message=recovery_data,
        )

        logger.info(
            "Recovery upload completed site_id=%s gateway_id=%s subtype=%s status=%s",
            location_id,
            gateway_id,
            msg_subtype,
            result.get("status"),
        )
        return Response(result)
