from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from listings.models import AdoptionListing
from listings.visibility import public_poster_q


class ListingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = AdoptionListing.objects.filter(listing_status="available")
        city = request.query_params.get("city")
        if city:
            qs = qs.filter(city=city)
        qs = qs.filter(public_poster_q()).distinct()
        results = [{"listing_id": str(l.listing_id),
                    "pet": {"name": l.name, "species": l.species, "breed": l.breed or None},
                    "city": l.city, "status": l.listing_status} for l in qs]
        return Response({"results": results, "next": None})


class ReportsMapView(APIView):
    """US-A1b · public guest rescue map (read-only, city-level, no auth). The data
    source is `stray_report`, a Sagip model that lands in Sprint 2 — until then this
    returns the contract shape with an empty set, so the guest surface is wired and
    the `signup-wall` on a gated tap can be built against it now."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"reports": []})
