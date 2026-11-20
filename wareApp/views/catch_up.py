"""Catch-up spread API (wareApp/catch_up_spread.py, docs/consumption/CATCH_UP_SPREAD.md)."""

from datetime import datetime, time, timedelta

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wareApp import catch_up_spread
from wareApp.models import CatchUpSpread, Site

__all__ = ["CatchUpSpreadApi"]

HISTORY_MAX_DAYS = 92


def _spread_dict(s, now, detail=False):
    body = {
        "id": s.id, "leg_id": s.leg_id, "aisle_name": getattr(s.aisle_group, "aisleGroupName", ""),
        "catch_up_at": f"{s.catch_up_at:%Y/%m/%d %H:%M}", "original_kwh": round(s.original_kwh, 2),
        "gap_from": f"{s.gap_from:%Y/%m/%d %H:%M}", "hours": s.hours, "share_kwh": round(s.share_kwh, 3),
        "mode": s.mode, "applied_by": s.applied_by, "applied_at": f"{s.applied_at:%Y/%m/%d %H:%M}",
        "undone_at": f"{s.undone_at:%Y/%m/%d %H:%M}" if s.undone_at else None,
        "undo_until": f"{catch_up_spread.undo_until(s):%Y/%m/%d %H:%M}",
        "can_undo": catch_up_spread.can_undo(s, now),
        "empty_hours": sum(1 for h in s.hours_detail if h.get("kind") == catch_up_spread.EMPTY),
        "no_data_hours": sum(1 for h in s.hours_detail if h.get("kind") == catch_up_spread.NO_DATA),
    }
    if detail:
        body["hours_detail"] = s.hours_detail
    return body


def _applied_spreads(site, day, now):
    """Spreads of this site's catch-up hours on ``day`` that are not undone (Undo for 5 days)."""
    rows = (
        CatchUpSpread.objects.filter(site=site, catch_up_at__date=day, undone_at__isnull=True)
        .select_related("aisle_group").order_by("catch_up_at", "id")
    )
    return [_spread_dict(s, now) for s in rows]


def _history(site, data, now):
    """All spreads of the site whose catch-up hour is in [from, to] (newest first), with their hours."""
    to_day = catch_up_spread.parse_day(data.get("to") or now.date())
    from_day = catch_up_spread.parse_day(data.get("from") or (to_day - timedelta(days=30)))
    if from_day > to_day:
        raise catch_up_spread.SpreadError("from is after to")
    if (to_day - from_day).days > HISTORY_MAX_DAYS:
        raise catch_up_spread.SpreadError(f"history covers at most {HISTORY_MAX_DAYS} days")
    rows = (
        CatchUpSpread.objects.filter(
            site=site, catch_up_at__gte=datetime.combine(from_day, time.min),
            catch_up_at__lt=datetime.combine(to_day + timedelta(days=1), time.min),
        ).select_related("aisle_group").order_by("-catch_up_at", "-id")
    )
    return {"status": 200, "site_id": site.id, "from": f"{from_day:%Y/%m/%d}", "to": f"{to_day:%Y/%m/%d}",
            "count": len(rows), "spreads": [_spread_dict(s, now, detail=True) for s in rows]}


class CatchUpSpreadApi(APIView):
    """Preview / apply / undo / history of spreading catch-up hours over their gap (Super_Admin only).

    POST /api/catchUpSpread/
    {"site_id": 114, "day": "2026/11/16", "legs": ["692"], "apply": false}   # preview (default)
    {"site_id": 114, "day": "2026/11/16", "legs": ["692"], "apply": true}    # spread (manual)
    {"undo": 12}                                                            # undo spread 12 (5 days)
    {"site_id": 114, "history": true, "from": "2026/11/01", "to": "2026/11/20"}  # spreads, per hour
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.UserType != 1:
            raise PermissionDenied("Only Super_Admin users can spread catch-up hours.")
        data = request.data
        now = datetime.now()
        try:
            if data.get("undo"):
                spread = CatchUpSpread.objects.filter(id=data.get("undo")).first()
                if spread is None:
                    return Response({"status": 400, "error": "unknown spread id"}, status=400)
                reverted = catch_up_spread.undo(spread, request.user)
                return Response({"status": 200, "undone": spread.id, "hours_reverted": reverted,
                                 "estimated_hours_removed": reverted})
            site = Site.objects.filter(id=data.get("site_id")).first()
            if site is None:
                return Response({"status": 400, "error": "unknown site_id"}, status=400)
            if str(data.get("history", "")).lower() in ("1", "true", "yes"):
                return Response(_history(site, data, now))
            not_spreadable, waiting = [], []
            items = catch_up_spread.plan(site, data.get("day"), data.get("legs"), not_spreadable, waiting)
            day = catch_up_spread.parse_day(data.get("day"))
            body = {"status": 200, "applied": False, "catch_ups": [preview for _, preview in items],
                    "waiting": waiting, "not_spreadable": not_spreadable,
                    "applied_spreads": _applied_spreads(site, day, now)}
            if str(data.get("apply", "")).lower() in ("1", "true", "yes"):
                if not items:
                    return Response({"status": 400, "error": "no catch-up hour to spread"}, status=400)
                done = catch_up_spread.apply(site, items, request.user, CatchUpSpread.MANUAL)
                body["applied"] = True
                body["applied_spreads"] = _applied_spreads(site, day, now)
                body["spreads"] = [{"id": s.id, "leg_id": s.leg_id, "catch_up_at": f"{s.catch_up_at:%Y/%m/%d %H:%M}",
                                    "hours": s.hours, "share_kwh": round(s.share_kwh, 3), "mode": s.mode}
                                   for s in done]
        except catch_up_spread.SpreadError as error:
            return Response({"status": 400, "error": str(error)}, status=400)
        return Response(body)
