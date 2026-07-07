from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from wareApp.models import Site
from wareApp.recovery.processor import process_http_recovery


class RecoveryUploadAPIView(APIView):

    authentication_classes = []
    permission_classes = []

    def post(self, request):

        gateway_id = request.data.get("gateway_id")
        location_id = request.data.get("location_id")
        msg_type = request.data.get("msg_type")
        msg_subtype = request.data.get("msg_subtype")
        message = request.data.get("message")

        if not gateway_id:
            return Response(
                {
                    "status": False,
                    "message": "gateway_id missing"
                },
                status=400
            )

        try:

            site = Site.objects.get(id=location_id)

        except Exception:

            return Response(
                {
                    "status": False,
                    "message": "Invalid Site"
                },
                status=404
            )

        result = process_http_recovery(
            site,
            gateway_id,
            location_id,
            msg_type,
            msg_subtype,
            message
        )

        return Response(result)