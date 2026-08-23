"""US-A2 — POST /listings, PATCH /listings/{id}: create/edit with the fee cap."""
import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from listings.models import AdoptionListing, AdoptionListingPhoto
from shelter.models import ShelterProfile
from verifications.models import AccountCapability, VerificationRequest


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


VALID_BODY = {
    "pet": {"name": "Bantay", "species": "dog", "breed": "Aspin", "sex": "male",
           "birthdate": "2023-01-15"},
    "description": "Friendly and house-trained.",
    "adoption_fee": "300.00",
    "city": "Marikina",
    "photos": [{"file_url": "https://example.invalid/1"}],
}


def _verified_member():
    acc = AccountFactory()
    AccountCapability.objects.create(account=acc, capability="rescuer", status="approved",
                                     granted_at=timezone.now())
    return acc


def _tier1_shelter():
    acc = AccountFactory(account_type="shelter")
    VerificationRequest.objects.create(account=acc, type="shelter_org", status="approved")
    ShelterProfile.objects.create(account=acc, org_name="Community Rescue", org_type="rescue",
                                  tier="community_rescue")
    return acc


def _tier2_shelter():
    acc = AccountFactory(account_type="shelter")
    VerificationRequest.objects.create(account=acc, type="shelter_org", status="approved")
    ShelterProfile.objects.create(account=acc, org_name="Registered NGO", org_type="shelter",
                                  tier="registered_ngo")
    return acc


# ── Gate ──────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_an_unverified_account_cannot_create_a_listing(client):
    plain = AccountFactory()
    res = client.post("/api/v1/listings", VALID_BODY, content_type="application/json",
                      **_hdr(plain))
    assert res.status_code == 403


@pytest.mark.django_db
def test_a_guest_is_401d(client):
    res = client.post("/api/v1/listings", VALID_BODY, content_type="application/json")
    assert res.status_code == 401


# ── Fee cap: Verified Member ─────────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_verified_member_can_create_at_or_under_the_cap(client):
    member = _verified_member()
    res = client.post("/api/v1/listings", VALID_BODY, content_type="application/json",
                      **_hdr(member))
    assert res.status_code == 201


@pytest.mark.django_db
def test_a_verified_member_over_the_cap_is_rejected(client):
    member = _verified_member()
    body = {**VALID_BODY, "adoption_fee": "501.00"}
    res = client.post("/api/v1/listings", body, content_type="application/json", **_hdr(member))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "fee_over_cap"
    assert res.json()["error"]["details"]["cap"] == 500
    assert AdoptionListing.objects.count() == 0


# ── Fee cap: tier-1 vs tier-2 shelters ───────────────────────────────────────────
@pytest.mark.django_db
def test_a_tier1_shelter_over_the_cap_is_rejected(client):
    shelter = _tier1_shelter()
    body = {**VALID_BODY, "adoption_fee": "501.00"}
    res = client.post("/api/v1/listings", body, content_type="application/json", **_hdr(shelter))
    assert res.status_code == 422


@pytest.mark.django_db
def test_a_tier2_shelter_is_uncapped(client):
    shelter = _tier2_shelter()
    body = {**VALID_BODY, "adoption_fee": "5000.00"}
    res = client.post("/api/v1/listings", body, content_type="application/json", **_hdr(shelter))
    assert res.status_code == 201


# ── Field mapping + photos ───────────────────────────────────────────────────────
@pytest.mark.django_db
def test_created_listing_fields_map_correctly(client):
    member = _verified_member()
    res = client.post("/api/v1/listings", VALID_BODY, content_type="application/json",
                      **_hdr(member))
    listing = AdoptionListing.objects.get(pk=res.json()["listing_id"])
    assert listing.name == "Bantay" and listing.species == "dog" and listing.breed == "Aspin"
    assert listing.sex == "male" and str(listing.date_of_birth) == "2023-01-15"
    assert listing.story == "Friendly and house-trained."   # description -> story
    assert str(listing.adoption_fee) == "300.00"
    assert listing.city == "Marikina"
    assert listing.posted_by_id == member.pk
    assert listing.status == "available"
    assert AdoptionListingPhoto.objects.filter(listing=listing).count() == 1


@pytest.mark.django_db
def test_response_shape(client):
    member = _verified_member()
    res = client.post("/api/v1/listings", VALID_BODY, content_type="application/json",
                      **_hdr(member))
    body = res.json()
    assert set(body.keys()) == {"listing_id", "listing_status"}
    assert body["listing_status"] == "available"


# ── PATCH ─────────────────────────────────────────────────────────────────────────
def _create_listing(client, poster, fee="300.00"):
    body = {**VALID_BODY, "adoption_fee": fee}
    res = client.post("/api/v1/listings", body, content_type="application/json", **_hdr(poster))
    return res.json()["listing_id"]


@pytest.mark.django_db
def test_the_poster_can_patch_their_own_listing(client):
    member = _verified_member()
    listing_id = _create_listing(client, member)
    res = client.patch(f"/api/v1/listings/{listing_id}", {"adoption_fee": "450.00"},
                       content_type="application/json", **_hdr(member))
    assert res.status_code == 200
    listing = AdoptionListing.objects.get(pk=listing_id)
    assert str(listing.adoption_fee) == "450.00"
    assert listing.name == "Bantay"  # untouched fields survive a partial update


@pytest.mark.django_db
def test_someone_else_cannot_patch_the_listing(client):
    member = _verified_member()
    listing_id = _create_listing(client, member)
    someone_else = _verified_member()
    res = client.patch(f"/api/v1/listings/{listing_id}", {"adoption_fee": "10.00"},
                       content_type="application/json", **_hdr(someone_else))
    assert res.status_code == 403


@pytest.mark.django_db
def test_patch_re_validates_the_fee_cap(client):
    member = _verified_member()
    listing_id = _create_listing(client, member, fee="100.00")
    res = client.patch(f"/api/v1/listings/{listing_id}", {"adoption_fee": "999.00"},
                       content_type="application/json", **_hdr(member))
    assert res.status_code == 422
    listing = AdoptionListing.objects.get(pk=listing_id)
    assert str(listing.adoption_fee) == "100.00"  # unchanged — the bad patch never applied


@pytest.mark.django_db
def test_patch_unknown_listing_is_404(client):
    import uuid
    member = _verified_member()
    res = client.patch(f"/api/v1/listings/{uuid.uuid4()}", {"adoption_fee": "1.00"},
                       content_type="application/json", **_hdr(member))
    assert res.status_code == 404
