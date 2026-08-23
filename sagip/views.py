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
from sagip.serializers import CaseStatusUpdateSerializer, OfferCreateSerializer, ReportCreateSerializer
from sagip.status import set_report_status

DEFAULT_RADIUS_KM = 10.0
# decision 14: offers must outlive the longest claim window (24h) so a reopened case
# still has people to re-ask — if either number moves, move both.
OFFER_WINDOW_HOURS = 48

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


class ReportOffersView(APIView):
    """US-O1 · offer help on an unclaimed report — a non-exclusive commitment (decision
    12). Anyone signed in may offer (no verification gate — that's the point of the
    ladder's lower rung); allowed only while the report is `reported`, since a claimed or
    resolved case has nothing left to offer on. **Never moves `stray_report.status`** —
    an offer answers a different question than a claim does."""
    permission_classes = [IsAuthenticated]

    def post(self, request, report_id):
        report = StrayReport.objects.filter(pk=report_id).first()
        if report is None:
            return Response({"error": {"code": "not_found", "message": "No such report"}},
                            status=404)
        if report.status != StrayStatus.REPORTED:
            return Response({"error": {"code": "report_not_open",
                                       "message": "This report is no longer open for offers"}},
                            status=409)

        s = OfferCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        offer_type = s.validated_data["offer_type"]
        if ReportOffer.objects.filter(report=report, account=request.user,
                                      offer_type=offer_type).exists():
            return Response({"error": {"code": "already_offered",
                                       "message": "You already offered this"}}, status=409)

        expires_at = timezone.now() + timezone.timedelta(hours=OFFER_WINDOW_HOURS)
        try:
            offer = ReportOffer.objects.create(
                report=report, account=request.user, offer_type=offer_type,
                status=OfferStatus.OPEN, expires_at=expires_at)
        except IntegrityError:
            # Backstop for the UNIQUE(report, account, offer_type) constraint, same
            # belt-and-suspenders shape as the claim's IntegrityError handling.
            return Response({"error": {"code": "already_offered",
                                       "message": "You already offered this"}}, status=409)

        if report.reporter_account_id:
            notify(report.reporter_account, "offer_received",
                  title="Someone offered to help",
                  body=f"{request.user.display_name} can help with "
                       f"{offer.get_offer_type_display().lower()}.",
                  data={"report_id": str(report.pk), "offer_id": str(offer.pk)})

        return Response({"offer_id": str(offer.pk), "status": offer.status,
                         "expires_at": offer.expires_at.isoformat()}, status=201)


class ReportOfferWithdrawView(APIView):
    """US-O2 · withdraw an offer — allowed only while it's still `open`. That
    reversibility is what earns offers the right to be low-effort (decision 12); once
    matched or expired there's nothing left to take back. No `withdrawn` status exists
    in the DDL's `offer_status` enum, so withdrawing deletes the row rather than
    recording a fourth state."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, report_id, offer_id):
        offer = ReportOffer.objects.filter(pk=offer_id, report_id=report_id).first()
        if offer is None:
            return Response({"error": {"code": "not_found", "message": "No such offer"}},
                            status=404)
        if offer.account_id != request.user.pk:
            return Response({"error": {"code": "not_your_offer",
                                       "message": "You can only withdraw your own offer"}},
                            status=403)
        if offer.status != OfferStatus.OPEN:
            return Response({"error": {"code": "not_withdrawable",
                                       "message": "This offer can no longer be withdrawn"}},
                            status=409)
        offer.delete()
        return Response(status=204)


class MyOffersView(APIView):
    """US-O2 · the caller's own offers, newest first — the client groups them into
    Open / Matched / Expired."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (ReportOffer.objects.filter(account=request.user)
              .select_related("report").order_by("-created_at"))
        offers = [{
            "offer_id": str(o.pk),
            "report": {"species": o.report.species, "condition": o.report.condition,
                      "city": o.report.city},
            "offer_type": o.offer_type,
            "status": o.status,
            "expires_at": o.expires_at.isoformat(),
        } for o in qs]
        return Response({"offers": offers})


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
    """US-S5 · public report detail (the shared-link case) + US-O3 · the reporter's
    waiting view. Base fields (species, condition, notes, photos, city, status) are
    Public — city-level, no precise geom, ever (§12.5). A reporter-only block
    (`escalation_level`, `offers_count`, `status_history`) is added ONLY when the
    authenticated caller IS this report's reporter — one route, two field-authorization
    tiers, checked by identity, never assumed from the mere presence of a bearer token."""
    permission_classes = [AllowAny]

    def get(self, request, report_id):
        r = StrayReport.objects.filter(pk=report_id).first()
        if r is None:
            return Response({"error": {"code": "not_found", "message": "No such report"}},
                            status=404)
        body = {
            "report_id": str(r.report_id), "species": r.species, "condition": r.condition,
            "status": r.status, "notes": r.notes or None, "city": r.city,
            "reported_at": r.created_at.isoformat(),
            "photos": [p.url for p in r.photos.order_by("uploaded_at")]}
        if request.user.is_authenticated and request.user.pk == r.reporter_account_id:
            body["escalation_level"] = r.escalation_level
            body["offers_count"] = r.offers.count()
            body["status_history"] = [
                {"status": h.status, "changed_at": h.changed_at.isoformat()}
                for h in r.status_history.order_by("changed_at")]
        return Response(body)
