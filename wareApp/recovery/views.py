from queue import Full

from rest_framework.views import APIView
from rest_framework.response import Response

from wareApp.models import Site
from .processor import process_http_recovery
from .service import recovery_queue


class RecoveryUploadAPIView(APIView):

    authentication_classes = []
    permission_classes = []

    def post(self, request):

        print("=" * 80)
        print("HTTP RECOVERY REQUEST")
        print(request.data)
        print("=" * 80)

        # topic = request.data.get("topic")
        # payload = request.data.get("payload")

        # if not topic:
        #     return Response({"status": False, "message": "topic missing"}, status=400)

        # if not payload:
        #     return Response({"status": False, "message": "payload missing"}, status=400)
        recovery_payload = request.data.get("Recovery Payload")

        if not recovery_payload:
            return Response(
                {
                    "status": False,
                    "message": "Recovery Payload missing",
                },
                status=400,
            )

        # try:

        # head = topic.split("/")

        # # Example:
        # # /Acclivate/iOmniControl/179/avc_test_gateway/in/recovery/hourlyConsumption

        # location_id = int(head[3])

        # gateway_id = head[4]

        # msg_type = head[6]

        # msg_subtype = head[7]

        # print("Location :", location_id)
        # print("Gateway  :", gateway_id)
        # print("Type     :", msg_type)
        # print("Subtype  :", msg_subtype)

        # except Exception as e:

        #     return Response({"status": False, "message": str(e)}, status=400)

        try:

            topic = recovery_payload[0]
            location_id = int(recovery_payload[1])
            gateway_id = recovery_payload[2]
            recovery_data = recovery_payload[3]
            # gw_total_cumulative = recovery_payload[4]
            head = topic.split("/")
            msg_type = head[6]
            msg_subtype = head[7]

            print("Topic      :", topic)
            print("Site       :", location_id)
            print("Gateway    :", gateway_id)
            print("Type       :", msg_type)
            print("Subtype    :", msg_subtype)

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": str(e),
                },
                status=400,
            )

        try:

            site = Site.objects.get(id=location_id)

        except Site.DoesNotExist:

            return Response({"status": False, "message": "Invalid Site"}, status=404)

        # result = process_http_recovery(
        #     site=site,
        #     gateway_id=gateway_id,
        #     location_id=location_id,
        #     msg_type=msg_type,
        #     msg_subtype=msg_subtype,
        #     message=payload,
        # )
        # result = process_http_recovery(
        #     site=site,
        #     gateway_id=gateway_id,
        #     location_id=location_id,
        #     msg_type=msg_type,
        #     msg_subtype=msg_subtype,
        #     message=recovery_data,
        # )

        job = {
            "site": site,
            "gateway_id": gateway_id,
            "location_id": location_id,
            "msg_type": msg_type,
            "msg_subtype": msg_subtype,
            "message": recovery_data,
        }

        try:
            recovery_queue.put(job, block=False)
            

        except Full:
            return Response(
                {
                    "status": False,
                    "message": "Recovery queue is full. Please try again later.",
                },
                status=503,
            )

        return Response({"status": True, "queued": True}, status=200)
