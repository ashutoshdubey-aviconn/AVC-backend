from queue import Full

from rest_framework.views import APIView
from rest_framework.response import Response

from .service import enqueue_recovery
from wareApp.models import Site
from django.http import HttpResponse


class RecoveryUploadAPIView(APIView):

    authentication_classes = []
    permission_classes = []
    throttle_classes = []  # disable DRF throttling for high-rate recovery ingestion

    def post(self, request):

        # receive recovery payload

        # topic = request.data.get("topic")dd a small script to push test payloads and assert coalescing behavior?
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

            # parsed topic and payload

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": str(e),
                },
                status=400,
            )

        # Do not hit the DB in the request path to avoid exhausting DB connections
        # The worker will resolve `site` from `location_id` when processing.

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
            "gateway_id": gateway_id,
            "location_id": location_id,
            "msg_type": msg_type,
            "msg_subtype": msg_subtype,
            "message": recovery_data,
        }

        try:
            enqueue_recovery(job)

        except Full:
            return Response(
                {
                    "status": False,
                    "message": "Recovery queue is full. Please try again later.",
                },
                status=503,
            )

        return Response({"status": True, "queued": True}, status=200)


class RecoveryHealthAPIView(APIView):
    """Return Redis queue depth and coalesced payload count for recovery."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        from django.conf import settings

        try:
            import redis
        except Exception:
            return Response(
                {"redis": False, "error": "redis package not installed"}, status=500
            )

        try:
            client = redis.Redis.from_url(
                getattr(settings, "REDIS_URL", "redis://localhost:6379/1"),
                decode_responses=True,
            )
            client.ping()
        except Exception as e:
            return Response({"redis": False, "error": str(e)}, status=200)

        queue_name = getattr(settings, "RECOVERY_QUEUE_NAME", "recovery:queue:v1")
        payload_pattern = "recovery:payload:*"

        try:
            queue_len = client.llen(queue_name)
        except Exception:
            queue_len = None

        # Count payload keys via SCAN (safe for production-sized sets if reasonably small)
        try:
            count = 0
            cur = 0
            while True:
                cur, keys = client.scan(cur, match=payload_pattern, count=1000)
                count += len(keys)
                if cur == 0:
                    break
            payload_count = count
        except Exception:
            payload_count = None

        return Response(
            {
                "redis": True,
                "queue_name": queue_name,
                "queue_length": queue_len,
                "pending_payloads": payload_count,
            }
        )


class RecoveryMetricsAPIView(APIView):
    """Expose Prometheus metrics for recovery (if prometheus_client installed).

    Returns 501 if `prometheus_client` is not available.
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        except Exception:
            return Response({"error": "prometheus_client not installed"}, status=501)

        try:
            data = generate_latest()
            return HttpResponse(data, content_type=CONTENT_TYPE_LATEST)
        except Exception as e:
            return Response({"error": str(e)}, status=500)
