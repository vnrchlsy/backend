from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import transaction
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from sagip.geo import centroid_for
from sagip.models import StrayReport, StrayReportPhoto
from sagip.serializers import ReportCreateSerializer

DEFAULT_RADIUS_KM = 10.0


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
