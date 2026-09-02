"""US-V2 — GET /me/verifications: the applicant's own document tracker."""
import pytest

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from verifications.models import VerificationDocument, VerificationRequest


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


@pytest.mark.django_db
def test_requires_auth(client):
    assert client.get("/api/v1/me/verifications").status_code == 401


@pytest.mark.django_db
def test_returns_the_callers_request_with_nested_documents(client):
    acc = AccountFactory()
    vr = VerificationRequest.objects.create(account=acc, type="shelter_org",
                                            status="needs_info", notes="Please replace billing.")
    VerificationDocument.objects.create(verification=vr, doc_type="proof_billing",
                                        file_url="https://example.invalid/b",
                                        status="rejected", review_note="Too dark.")
    body = client.get("/api/v1/me/verifications", **_hdr(acc)).json()["verifications"]
    assert len(body) == 1
    v = body[0]
    assert v["verification_id"] == str(vr.verification_id)
    assert v["type"] == "shelter_org" and v["status"] == "needs_info"
    assert v["notes"] == "Please replace billing."
    doc = v["documents"][0]
    assert doc["doc_type"] == "proof_billing"
    assert doc["status"] == "rejected"
    assert doc["review_note"] == "Too dark."
    assert doc["superseded_by"] is None


@pytest.mark.django_db
def test_only_returns_the_callers_own_requests(client):
    me, other = AccountFactory(), AccountFactory()
    VerificationRequest.objects.create(account=other, type="rescuer")
    assert client.get("/api/v1/me/verifications", **_hdr(me)).json()["verifications"] == []


@pytest.mark.django_db
def test_superseded_by_points_at_the_replacement(client):
    acc = AccountFactory()
    vr = VerificationRequest.objects.create(account=acc, type="shelter_org")
    old = VerificationDocument.objects.create(verification=vr, doc_type="gov_id",
                                              file_url="https://example.invalid/old", status="rejected")
    new = VerificationDocument.objects.create(verification=vr, doc_type="gov_id",
                                              file_url="https://example.invalid/new")
    old.superseded_by = new
    old.save(update_fields=["superseded_by"])
    docs = {d["document_id"]: d
            for d in client.get("/api/v1/me/verifications", **_hdr(acc)).json()["verifications"][0]["documents"]}
    assert docs[str(old.document_id)]["superseded_by"] == str(new.document_id)
