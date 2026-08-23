from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.service import notify
from sagip.geo import centroid_for
from sagip.models import OfferStatus, ReportOffer, RescueCase, StrayReport, StrayReportPhoto, StrayStatus
from sagip.permissions import IsVerifiedRescuer
from sagip.serializers import CaseStatusUpdateSerializer, ReportCreateSerializer
from sagip.status import set_report_status

DEFAULT_RADIUS_KM = 10.0

# US-K2 · a case can only move forward through this order; `resolved` is terminal.
# `claimed` is included as the baseline so a target's index can be compared against
# whatever the report is currently at (never itself a valid POST target — see the
# serializer's choices).
CASE_STATUS_ORDER = {
    StrayStatus.CLAIMED: 0,
    StrayStatus.RESCUED: 1,
    StrayStatus.SAFE: 2,
    StrayStatus.RESOLVED: 3,
}


def _already_claimed():
    return Response({"error": {"code": "already_claimed",
                               "message": "This report already has an active claim"}},
                    status=409)


class ReportsCreateView(APIView):
    """US-S1 · report a stray. A guest tapping this gets 401 (the client raises the signup
    wall and resumes the report after signup). `is_anonymous` hides the reporter from other
    users, but the row still records `reporter_account_id`."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = ReportCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        with transaction.atomic():
            report = StrayReport.objects.create(
                reporter_account=request.user,
                is_anonymous=d.get("is_anonymous", False),
                species=d["species"], condition=d["condition"], notes=d.get("notes", ""),
                geom=Point(d["lng"], d["lat"], srid=4326),   # PostGIS: (x=lng, y=lat)
                location_text=d.get("location_text", ""),
                city=(d.get("city") or "").strip() or None,   # client-resolved city label, or NULL
                status="reported", escalation_level=0)
            for photo in d.get("photos", []):
                StrayReportPhoto.objects.create(report=report, url=photo["file_url"])
        return Response({"report_id": str(report.report_id), "status": "reported"}, status=201)


class ReportClaimView(APIView):
    """US-K1 · claim an unclaimed report — exclusive and binding (decision 11). Only an
    approved rescuer capability (Verified Member) or an approved shelter_org verification
    (verified shelter) may claim (IsVerifiedRescuer); an unverified caller gets 403.

    Creating the case, moving the report to `claimed` (via `set_report_status`, so it's
    logged), matching every open offer on the report, and notifying the reporter + each
    matched offerer all happen inside one transaction — a claim that partially lands
    (case created but offers left dangling, or vice versa) is worse than no claim.

    Exclusivity is enforced twice: a `select_for_update` existence check inside the
    transaction (serializes concurrent requests on the same report and returns a clean
    409), backed by the partial-unique DB constraint (`idx_rescue_case_active`) as the
    real safety net — an `IntegrityError` that slips past the check still becomes a 409,
    never a 500."""
    permission_classes = [IsVerifiedRescuer]

    def post(self, request, report_id):
        try:
            with transaction.atomic():
                report = (StrayReport.objects.select_for_update()
                          .filter(pk=report_id).first())
                if report is None:
                    return Response({"error": {"code": "not_found",
                                               "message": "No such report"}}, status=404)
                if RescueCase.objects.filter(report=report, expired_at__isnull=True).exists():
                    return _already_claimed()

                case = RescueCase.objects.create(report=report, claimed_by_account=request.user)
                set_report_status(report, StrayStatus.CLAIMED, request.user)

                offers = ReportOffer.objects.select_for_update().filter(
                    report=report, status=OfferStatus.OPEN)
                for offer in offers:
                    offer.status = OfferStatus.MATCHED
                    offer.save(update_fields=["status"])
                    notify(offer.account, "offer_matched",
                          title="Your offer was matched",
                          body=f"Someone claimed the {report.get_species_display().lower()} "
                               f"you offered to help.",
                          data={"report_id": str(report.pk), "case_id": str(case.pk)})

                # The reporter is always notified — is_anonymous hides them from OTHER
                # users, never from their own report (rule 6).
                if report.reporter_account_id:
                    notify(report.reporter_account, "report_claimed",
                          title="Your report was claimed",
                          body=f"{request.user.display_name} is on the way.",
                          data={"report_id": str(report.pk), "case_id": str(case.pk)})
        except IntegrityError:
            return _already_claimed()

        return Response({"case_id": str(case.pk), "status": "claimed"}, status=201)


class CaseStatusView(APIView):
    """US-K2 · work a claimed case toward safe/resolved. Only the claimer may move it —
    an ownership check, not a role gate, since claiming already proved verification.
    Forward-only through CASE_STATUS_ORDER (never backward, never re-posting the current
    status); `resolved` is terminal. Every move goes through `set_report_status`, so it's
    what keeps a worked case from looking stalled to US-E2's auto-expiry sweep."""
    permission_classes = [IsAuthenticated]

    def post(self, request, case_id):
        case = RescueCase.objects.select_related("report").filter(pk=case_id).first()
        if case is None:
            return Response({"error": {"code": "not_found", "message": "No such case"}},
                            status=404)
        if case.claimed_by_account_id != request.user.pk:
            return Response({"error": {"code": "not_your_case",
                                       "message": "Only the claimer can update this case"}},
                            status=403)
        if case.expired_at is not None:
            return Response({"error": {"code": "case_expired",
                                       "message": "This claim has lapsed"}}, status=409)

        s = CaseStatusUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        target = s.validated_data["status"]

        report = case.report
        current_rank = CASE_STATUS_ORDER.get(report.status, -1)
        if report.status == StrayStatus.RESOLVED:
            return Response({"error": {"code": "case_resolved",
                                       "message": "This case is already resolved"}}, status=409)
        if CASE_STATUS_ORDER[target] <= current_rank:
            return Response({"error": {"code": "not_forward",
                                       "message": "A case can only move forward"}}, status=409)

        with transaction.atomic():
            set_report_status(report, target, request.user, note=s.validated_data.get("note", ""))
            if target == StrayStatus.RESOLVED:
                if "outcome_notes" in s.validated_data:
                    case.outcome_notes = s.validated_data["outcome_notes"]
                if "outcome_photo_url" in s.validated_data:
                    case.outcome_photo_url = s.validated_data["outcome_photo_url"]
                case.resolved_at = timezone.now()
                case.save(update_fields=["outcome_notes", "outcome_photo_url", "resolved_at"])

        return Response({"status": target}, status=200)


class MyRescuesView(APIView):
    """US-K3 · the claimer's own cases — active, resolved, and expired — newest claim
    first. This is the claimer's home for the rescue loop."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (RescueCase.objects.filter(claimed_by_account=request.user)
              .select_related("report").order_by("-claimed_at"))
        cases = [{
            "case_id": str(c.pk),
            "report": {"species": c.report.species, "condition": c.report.condition,
                      "city": c.report.city},
            "status": c.report.status,
            "claimed_at": c.claimed_at.isoformat(),
            "expired_at": c.expired_at.isoformat() if c.expired_at else None,
        } for c in qs]
        return Response({"cases": cases})


class RescueMapView(APIView):
    """US-S4 · the public rescue map. Anyone (signed in or not) sees strays near a chosen
    city — a PostGIS proximity query ordered by distance from the city centroid, within a
    radius. Replaces the Sprint-1 stub at the same route.

    ⚠️ City-level only (§12.5): the response never carries the precise `geom`. The exact
    spot is what US-S2 disclosed as the report's one precise-GPS surface; handing it to
    anonymous callers here would quietly undo that. The map places pins at city
    granularity, not the reporter's exact location."""
    permission_classes = [AllowAny]

    def get(self, request):
        centroid_ll = centroid_for(request.query_params.get("city"))
        if centroid_ll is None:
            return Response({"reports": []})  # the map is city-scoped; no known city, nothing to show
        lat, lng = centroid_ll
        centroid = Point(lng, lat, srid=4326)
        try:
            radius_km = float(request.query_params.get("radius_km") or DEFAULT_RADIUS_KM)
        except (TypeError, ValueError):
            radius_km = DEFAULT_RADIUS_KM
        qs = (StrayReport.objects
              .filter(geom__dwithin=(centroid, D(km=radius_km)))
              .annotate(_distance=Distance("geom", centroid))
              .order_by("_distance"))
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        city = request.query_params.get("city")
        reports = [{"report_id": str(r.report_id), "species": r.species,
                    "condition": r.condition, "status": r.status,
                    "city": r.city or city,   # coarse label; precise geom deliberately withheld
                    "reported_at": r.created_at.isoformat()}
                   for r in qs]
        return Response({"reports": reports})


class MyReportsView(APIView):
    """US-S3 · the reporter's own list, with live status. Their own reports, so the list
    is theirs to see — still city-level fields, no precise coordinate echoed back."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = request.user.stray_reports.order_by("-created_at")
        results = [{"report_id": str(r.report_id), "species": r.species,
                    "condition": r.condition, "status": r.status,
                    "city": r.city, "created_at": r.created_at.isoformat()} for r in qs]
        return Response({"results": results})


class ReportDetailView(APIView):
    """US-S5 · public report detail (the shared-link case). Condition, notes, photos, city,
    time, status — city-level, no precise geom, and no claim button this sprint (the claim
    and offers ladder are Sprint 3)."""
    permission_classes = [AllowAny]

    def get(self, request, report_id):
        r = StrayReport.objects.filter(pk=report_id).first()
        if r is None:
            return Response({"error": {"code": "not_found", "message": "No such report"}},
                            status=404)
        return Response({
            "report_id": str(r.report_id), "species": r.species, "condition": r.condition,
            "status": r.status, "notes": r.notes or None, "city": r.city,
            "reported_at": r.created_at.isoformat(),
            "photos": [p.url for p in r.photos.order_by("uploaded_at")]})
