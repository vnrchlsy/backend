from django.db import IntegrityError, transaction
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Address
from listings.fees import fee_cap_for
from listings.models import (AdoptionInquiry, AdoptionListing, AdoptionListingPhoto,
                             AdoptionStage, AdoptionStageKey, StageState)
from listings.permissions import IsVerifiedMember
from listings.serializers import (InquiryCreateSerializer, ListingCreateSerializer,
                                  ListingPatchSerializer, StageUpdateSerializer)
from listings.stages import set_stage_state
from listings.visibility import public_poster_q
from notifications.service import notify
from shelter.models import ShelterProfile

PAGE_SIZE = 20


def _paginate(qs, request):
    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    start = (page - 1) * PAGE_SIZE
    items = list(qs[start:start + PAGE_SIZE + 1])
    has_next = len(items) > PAGE_SIZE
    return items[:PAGE_SIZE], (page + 1 if has_next else None)


def _pet_fields(listing):
    return {"name": listing.name, "species": listing.species, "breed": listing.breed or None,
            "sex": listing.sex or None,
            "birthdate": listing.date_of_birth.isoformat() if listing.date_of_birth else None,
            "size_category": listing.size_category or None,
            "spayed_neutered": listing.spayed_neutered,
            "vaccinated": listing.vaccinated, "walkable": listing.walkable,
            "temperament": listing.temperament or None}


def _card(listing):
    photo = listing.photos.filter(is_primary=True).first() or listing.photos.first()
    return {"listing_id": str(listing.listing_id), "pet": _pet_fields(listing),
            "city": listing.city, "status": listing.status,
            "adoption_fee": str(listing.adoption_fee),
            "photo_url": photo.url if photo else None}


def _poster_info(account):
    profile = ShelterProfile.objects.filter(account=account).first()
    addr = Address.objects.filter(account=account, is_primary=True).first()
    # account_id lets the client link to US-Q2's public donate surface
    # (GET /shelters/{account_id}/donation-qr) for a shelter poster.
    return {"account_id": str(account.pk), "name": profile.org_name if profile else account.display_name,
            "is_shelter": profile is not None, "city": addr.city if addr else None}


class ListingsView(APIView):
    """GET /listings (US-A1b, extended by US-A3) · POST /listings (US-A2).

    ⚠️ Creation is gated on `IsAuthenticated`, NOT verification. Decision 2 ("Shelter
    gating = draft-only, gated-public") — an unverified shelter (or an owner without the
    Verified Member badge) may still draft a listing; it simply never appears in `GET
    /listings`, which filters through `public_poster_q()`. Gating creation itself on
    `IsVerifiedRescuer` would have blocked exactly the drafting flow decision 2 requires —
    caught while wiring the mobile create form, before it shipped."""

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get(self, request):
        if request.query_params.get("mine") == "true":
            if not request.user or not request.user.is_authenticated:
                return Response({"error": {"code": "auth_required",
                                           "message": "Log in first"}}, status=401)
            qs = (AdoptionListing.objects.filter(status="available", posted_by=request.user)
                  .order_by("-created_at"))
            page_items, next_page = _paginate(qs, request)
            return Response({"results": [_card(l) for l in page_items], "next": next_page})
        qs = (AdoptionListing.objects.filter(status="available")
              .filter(public_poster_q()).distinct().order_by("-created_at"))
        city = request.query_params.get("city")
        if city:
            qs = qs.filter(city=city)
        species = request.query_params.get("species")
        if species:
            qs = qs.filter(species=species)
        page_items, next_page = _paginate(qs, request)
        return Response({"results": [_card(l) for l in page_items], "next": next_page})

    def post(self, request):
        s = ListingCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        cap = fee_cap_for(request.user)
        if cap is not None and data["adoption_fee"] > cap:
            return Response({"error": {"code": "fee_over_cap",
                                       "message": f"The adoption fee can't exceed ₱{cap}",
                                       "details": {"cap": cap}}}, status=422)
        pet = data["pet"]
        with transaction.atomic():
            listing = AdoptionListing.objects.create(
                posted_by=request.user, name=pet["name"], species=pet["species"],
                breed=pet.get("breed", ""), sex=pet.get("sex", ""),
                date_of_birth=pet.get("birthdate"), city=data["city"],
                story=data.get("description", ""), adoption_fee=data["adoption_fee"])
            for photo in data.get("photos", []):
                AdoptionListingPhoto.objects.create(listing=listing, url=photo["file_url"])
        return Response({"listing_id": str(listing.pk), "listing_status": listing.status},
                        status=201)


class ListingDetailView(APIView):
    """GET /listings/{id} (US-A3, Public) · PATCH /listings/{id} (US-A2, poster-only —
    ownership is the real gate here, not verification; see ListingsView's note)."""

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get(self, request, listing_id):
        listing = AdoptionListing.objects.filter(pk=listing_id).first()
        if listing is None:
            return Response({"error": {"code": "not_found", "message": "No such listing"}},
                            status=404)
        return Response({
            "listing_id": str(listing.pk), "pet": _pet_fields(listing),
            "description": listing.story or None, "adoption_fee": str(listing.adoption_fee),
            "requirements": listing.requirements or None, "city": listing.city,
            "status": listing.status,
            "photos": [p.url for p in listing.photos.all()],
            "poster": _poster_info(listing.posted_by),
        })

    def patch(self, request, listing_id):
        listing = AdoptionListing.objects.filter(pk=listing_id).first()
        if listing is None:
            return Response({"error": {"code": "not_found", "message": "No such listing"}},
                            status=404)
        if listing.posted_by_id != request.user.pk:
            return Response({"error": {"code": "not_your_listing",
                                       "message": "Only the poster can edit this listing"}},
                            status=403)
        s = ListingPatchSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        if "adoption_fee" in data:
            cap = fee_cap_for(request.user)
            if cap is not None and data["adoption_fee"] > cap:
                return Response({"error": {"code": "fee_over_cap",
                                           "message": f"The adoption fee can't exceed ₱{cap}",
                                           "details": {"cap": cap}}}, status=422)
        field_map = {"birthdate": "date_of_birth", "description": "story"}
        for key, value in data.items():
            setattr(listing, field_map.get(key, key), value)
        listing.save()
        return Response({
            "listing_id": str(listing.pk), "pet": _pet_fields(listing),
            "description": listing.story or None, "adoption_fee": str(listing.adoption_fee),
            "city": listing.city, "status": listing.status,
        })


class ListingInquiriesView(APIView):
    """POST /listings/{id}/inquiries — US-A4. Only a Verified Member with a verified
    phone may inquire; the phone check exists because the inquiry is the first
    contact-exchange moment ("verify-phone ships with its first trigger")."""
    permission_classes = [IsVerifiedMember]

    def post(self, request, listing_id):
        listing = AdoptionListing.objects.filter(pk=listing_id).first()
        if listing is None:
            return Response({"error": {"code": "not_found", "message": "No such listing"}},
                            status=404)
        if request.user.phone_verified_at is None:
            return Response({"error": {"code": "phone_unverified",
                                       "message": "Verify your phone before inquiring"}},
                            status=403)
        s = InquiryCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        if AdoptionInquiry.objects.filter(listing=listing, adopter_account=request.user).exists():
            return Response({"error": {"code": "already_inquired",
                                       "message": "You already inquired on this listing"}},
                            status=409)
        try:
            with transaction.atomic():
                inquiry = AdoptionInquiry.objects.create(
                    listing=listing, adopter_account=request.user,
                    message=s.validated_data.get("message", ""))
                stages = []
                for key in AdoptionStageKey:
                    stage = AdoptionStage.objects.create(inquiry=inquiry, stage_key=key)
                    stages.append(stage)
                # The 'inquiry' stage completes itself — submitting IS that stage
                # happening. Logged like any other transition (set_stage_state), not
                # silently defaulted, so the history is complete from the first row.
                inquiry_stage = next(st for st in stages if st.stage_key == AdoptionStageKey.INQUIRY)
                set_stage_state(inquiry_stage, StageState.DONE, request.user)
                notify(listing.posted_by, "inquiry_received",
                      title="Someone inquired about your listing",
                      body=f"{request.user.display_name} is interested in {listing.name}.",
                      data={"listing_id": str(listing.pk), "inquiry_id": str(inquiry.pk)})
        except IntegrityError:
            return Response({"error": {"code": "already_inquired",
                                       "message": "You already inquired on this listing"}},
                            status=409)
        return Response({"inquiry_id": str(inquiry.pk), "status": inquiry.status}, status=201)


class MyInquiriesView(APIView):
    """GET /me/inquiries — US-A4. The adopter's own inquiries, with each stage's state,
    so "both sides see the same state" is literal: this is the same data the poster's
    stage-advance writes into."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (AdoptionInquiry.objects.filter(adopter_account=request.user)
              .select_related("listing").order_by("-created_at"))
        page_items, next_page = _paginate(qs, request)
        results = []
        for inquiry in page_items:
            stages = {s.stage_key: s.state for s in inquiry.stages.all()}
            results.append({
                "inquiry_id": str(inquiry.pk),
                "listing": {"listing_id": str(inquiry.listing_id), "name": inquiry.listing.name,
                           "species": inquiry.listing.species},
                "status": inquiry.status,
                "stages": [{"stage_key": key, "state": stages.get(key, StageState.NOT_STARTED)}
                          for key in AdoptionStageKey],
            })
        return Response({"results": results, "next": next_page})


class InquiryStageView(APIView):
    """POST /inquiries/{id}/stages/{stage_key} — US-A4. Only the listing's poster may
    advance a stage."""
    permission_classes = [IsAuthenticated]

    def post(self, request, inquiry_id, stage_key):
        inquiry = AdoptionInquiry.objects.select_related("listing").filter(pk=inquiry_id).first()
        if inquiry is None:
            return Response({"error": {"code": "not_found", "message": "No such inquiry"}},
                            status=404)
        if inquiry.listing.posted_by_id != request.user.pk:
            return Response({"error": {"code": "not_your_listing",
                                       "message": "Only the poster can advance this inquiry"}},
                            status=403)
        stage = inquiry.stages.filter(stage_key=stage_key).first()
        if stage is None:
            return Response({"error": {"code": "not_found", "message": "No such stage"}},
                            status=404)
        s = StageUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        set_stage_state(stage, s.validated_data["state"], request.user,
                        note=s.validated_data.get("note", ""))
        notify(inquiry.adopter_account, "stage_advanced",
              title="Your adoption inquiry moved forward",
              body=f"{stage_key.replace('_', ' ').title()} is now {s.validated_data['state'].replace('_', ' ')}.",
              data={"inquiry_id": str(inquiry.pk), "stage_key": stage_key})
        return Response({"stage_key": stage_key, "state": stage.state})
