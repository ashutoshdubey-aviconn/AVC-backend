"""Catch-up spread API (wareApp/catch_up_spread.py, docs/consumption/CATCH_UP_SPREAD.md)."""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp import catch_up_spread
from wareApp.models import CatchUpSpread, Site

__all__ = ["CatchUpSpreadApi"]


class CatchUpSpreadApi(APIView):
    """Preview / apply / undo spreading catch-up hours over their gap (Super_Admin only).

    POST /api/catchUpSpread/
    {"site_id": 114, "day": "2026/11/16", "legs": ["692"], "apply": false}   # preview (default)
    {"site_id": 114, "day": "2026/11/16", "legs": ["692"], "apply": true}    # spread
    {"undo": 12}                                                            # undo spread 12
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.UserType != 1:
            raise PermissionDenied("Only Super_Admin users can spread catch-up hours.")
        data = request.data
        try:
            if data.get("undo"):
                spread = CatchUpSpread.objects.filter(id=data.get("undo")).first()
                if spread is None:
                    return Response({"status": 400, "error": "unknown spread id"}, status=400)
                removed = catch_up_spread.undo(spread, request.user)
                return Response({"status": 200, "undone": spread.id, "estimated_hours_removed": removed})
            site = Site.objects.filter(id=data.get("site_id")).first()
            if site is None:
                return Response({"status": 400, "error": "unknown site_id"}, status=400)
            not_spreadable = []
            items = catch_up_spread.plan(site, data.get("day"), data.get("legs"), not_spreadable)
            body = {"status": 200, "applied": False, "catch_ups": [preview for _, preview in items],
                    "not_spreadable": not_spreadable}
            if str(data.get("apply", "")).lower() in ("1", "true", "yes"):
                if not items:
                    return Response({"status": 400, "error": "no catch-up hour to spread"}, status=400)
                done = catch_up_spread.apply(site, items, request.user)
                body["applied"] = True
                body["spreads"] = [{"id": s.id, "leg_id": s.leg_id, "catch_up_at": f"{s.catch_up_at:%Y/%m/%d %H:%M}",
                                    "hours": s.hours, "share_kwh": round(s.share_kwh, 3)} for s in done]
        except catch_up_spread.SpreadError as error:
            return Response({"status": 400, "error": str(error)}, status=400)
        return Response(body)
