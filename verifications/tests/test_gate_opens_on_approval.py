"""US-X2 — prove the visibility gates actually open on a real approval.

Sprint 1 wrote the `public_poster_q()` predicate and the dashboard gate derivation, but
had no way to approve anything, so the chain *decision → derived predicate → public output*
was never exercised end to end. US-R5's `approve_request` is now that decision. These tests
drive it and assert the public-facing endpoints change — no new plumbing, just proof (and a
regression guard) that approval alone flips a drafted listing to visible. Approval *is* the
gate; nothing is republished.
"""
import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from listings.models import AdoptionListing
from verifications.models import AccountCapability, VerificationRequest
from verifications.review import approve_request


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _reviewer():
    return AccountFactory(account_type="admin", email="rev@kupkop.ph")


@pytest.mark.django_db
def test_shelter_listing_is_hidden_while_pending_then_public_after_approval(client):
    reviewer = _reviewer()
    shelter = AccountFactory(account_type="shelter", email_verified_at=timezone.now())
    vr = VerificationRequest.objects.create(account=shelter, type="shelter_org",
                                            status="pending")
    AdoptionListing.objects.create(posted_by=shelter, name="Bantay", species="dog",
                                   city="Marikina")

    # drafted while pending → absent from the public feed
    assert client.get("/api/v1/listings?city=Marikina").json()["results"] == []

    approve_request(vr, reviewer)

    # the SAME listing is now public — no edit, no republish
    names = [r["pet"]["name"] for r in
             client.get("/api/v1/listings?city=Marikina").json()["results"]]
    assert "Bantay" in names


@pytest.mark.django_db
def test_shelter_dashboard_gates_flip_from_false_to_true_on_approval(client):
    reviewer = _reviewer()
    shelter = AccountFactory(account_type="shelter", email_verified_at=timezone.now())
    vr = VerificationRequest.objects.create(account=shelter, type="shelter_org",
                                            status="pending")

    before = client.get("/api/v1/shelter/dashboard", **_hdr(shelter)).json()["gates"]
    assert before == {"can_publish": False, "donations_enabled": False}

    approve_request(vr, reviewer)

    after = client.get("/api/v1/shelter/dashboard", **_hdr(shelter)).json()["gates"]
    # US-X3 · publishing opens on approval, but donations need a SECOND key (a reviewer-verified
    # QR), so donations_enabled stays False here — the two-key gate is proved in test_donation_gate.
    assert after == {"can_publish": True, "donations_enabled": False}


@pytest.mark.django_db
def test_verified_member_listing_goes_public_when_the_capability_is_granted(client):
    reviewer = _reviewer()
    member = AccountFactory(account_type="personal", email_verified_at=timezone.now())
    vr = VerificationRequest.objects.create(account=member, type="rescuer", status="pending")
    AccountCapability.objects.create(account=member, capability="rescuer", status="pending")
    AdoptionListing.objects.create(posted_by=member, name="Muning", species="cat",
                                   city="Pasig")

    # a Verified Member has no shelter_profile; the listing is gated on the capability
    assert client.get("/api/v1/listings?city=Pasig").json()["results"] == []

    approve_request(vr, reviewer)  # grants the rescuer capability

    names = [r["pet"]["name"] for r in
             client.get("/api/v1/listings?city=Pasig").json()["results"]]
    assert "Muning" in names
