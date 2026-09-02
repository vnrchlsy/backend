import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from shelter.models import ShelterProfile


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _shelter(tier):
    acc = AccountFactory(account_type="shelter", email_verified_at=timezone.now())
    ShelterProfile.objects.create(account=acc, org_name="PAWS", org_type="shelter", tier=tier)
    return acc


def _doc(t, n=1):
    return [{"doc_type": t, "file_url": f"https://x/{t}{i}.jpg"} for i in range(n)]


BASE = _doc("gov_id") + _doc("proof_billing") + _doc("rescue_photos", 3)


def _post(client, acc, **extra):
    body = {"type": "shelter_org", "consent_version": "2026-08-01", **extra}
    return client.post("/api/v1/verifications", body, content_type="application/json", **_hdr(acc))


# ---------- US-B4 · tier-1 (community_rescue) ----------

@pytest.mark.django_db
def test_tier1_full_set_accepted(client):
    acc = _shelter("community_rescue")
    res = _post(client, acc, documents=BASE)
    assert res.status_code == 201 and res.json()["status"] == "pending"


@pytest.mark.django_db
def test_tier1_missing_proof_billing_is_422(client):
    acc = _shelter("community_rescue")
    res = _post(client, acc, documents=_doc("gov_id") + _doc("rescue_photos", 3))
    assert res.status_code == 422 and res.json()["error"]["code"] == "missing_docs"


@pytest.mark.django_db
def test_tier1_two_photos_is_422_min_photos(client):
    acc = _shelter("community_rescue")
    res = _post(client, acc, documents=_doc("gov_id") + _doc("proof_billing") + _doc("rescue_photos", 2))
    body = res.json()
    assert res.status_code == 422 and body["error"]["details"]["min_photos"] == 3


@pytest.mark.django_db
def test_shelter_org_without_profile_is_409(client):
    acc = AccountFactory(account_type="shelter", email_verified_at=timezone.now())
    res = _post(client, acc, documents=BASE)
    assert res.status_code == 409 and res.json()["error"]["code"] == "no_profile"


@pytest.mark.django_db
def test_shelter_org_by_personal_account_is_403(client):
    acc = AccountFactory(account_type="personal", email_verified_at=timezone.now())
    res = _post(client, acc, documents=BASE)
    assert res.status_code == 403 and res.json()["error"]["code"] == "not_shelter"


# ---------- US-C1 · tier-2 (registered_ngo) ----------

@pytest.mark.django_db
def test_tier2_without_base_docs_is_409_tier1_incomplete(client):
    acc = _shelter("registered_ngo")
    res = _post(client, acc, documents=_doc("sec_dti") + _doc("bai_cert"))
    assert res.status_code == 409 and res.json()["error"]["code"] == "tier1_incomplete"


@pytest.mark.django_db
def test_tier2_base_but_missing_sec_is_422(client):
    acc = _shelter("registered_ngo")
    res = _post(client, acc, documents=BASE + _doc("bai_cert"))
    assert res.status_code == 422 and res.json()["error"]["code"] == "missing_docs"


@pytest.mark.django_db
def test_tier2_full_set_accepted(client):
    acc = _shelter("registered_ngo")
    res = _post(client, acc, documents=BASE + _doc("sec_dti") + _doc("bai_cert"))
    assert res.status_code == 201


@pytest.mark.django_db
def test_tier2_bai_pending_accepts_sec_without_bai(client):
    acc = _shelter("registered_ngo")
    res = _post(client, acc, documents=BASE + _doc("sec_dti"), bai_pending=True)
    assert res.status_code == 201
