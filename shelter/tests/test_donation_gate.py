"""US-X3 · donations are a two-key gate — org approved AND a reviewer-verified QR."""
import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from shelter.models import DonationQr
from verifications.models import VerificationRequest
from verifications.review import approve_request


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _approved_shelter():
    reviewer = AccountFactory(account_type="admin", email="rev-qr@kupkop.ph")
    shelter = AccountFactory(account_type="shelter", email_verified_at=timezone.now())
    vr = VerificationRequest.objects.create(account=shelter, type="shelter_org", status="pending")
    approve_request(vr, reviewer)
    return shelter


def _qr(account, verified):
    return DonationQr.objects.create(account=account, provider="gcash",
                                     account_name="Marikina AWG", qr_image_url="s3://qr/1",
                                     verified=verified)


def _donations_gate(client, acc):
    return client.get("/api/v1/shelter/dashboard", **_hdr(acc)).json()["gates"]["donations_enabled"]


@pytest.mark.django_db
def test_approved_org_without_a_qr_cannot_take_donations(client):
    shelter = _approved_shelter()
    assert _donations_gate(client, shelter) is False


@pytest.mark.django_db
def test_an_unverified_qr_does_not_open_donations(client):
    shelter = _approved_shelter()
    _qr(shelter, verified=False)
    assert _donations_gate(client, shelter) is False


@pytest.mark.django_db
def test_donations_open_only_with_approval_and_a_verified_qr(client):
    shelter = _approved_shelter()
    _qr(shelter, verified=True)
    assert _donations_gate(client, shelter) is True


@pytest.mark.django_db
def test_a_verified_qr_without_approval_still_cannot_take_donations(client):
    # Second key present, first key missing: an unapproved org never opens donations.
    shelter = AccountFactory(account_type="shelter", email_verified_at=timezone.now())
    VerificationRequest.objects.create(account=shelter, type="shelter_org", status="pending")
    _qr(shelter, verified=True)
    assert _donations_gate(client, shelter) is False
