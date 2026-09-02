"""US-V3 — POST /verifications/{id}/documents: replace a rejected file, superseding it."""
import pytest

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from verifications.models import VerificationDocument, VerificationRequest


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _url(vr):
    return f"/api/v1/verifications/{vr.verification_id}/documents"


def _rejected_doc_request(owner):
    vr = VerificationRequest.objects.create(account=owner, type="shelter_org", status="needs_info")
    doc = VerificationDocument.objects.create(verification=vr, doc_type="proof_billing",
                                              file_url="https://example.invalid/old", status="rejected")
    return vr, doc


def _body(doc, url="https://example.invalid/new"):
    return {"replaces": str(doc.document_id), "doc_type": doc.doc_type, "file_url": url}


@pytest.mark.django_db
def test_requires_auth(client):
    vr, doc = _rejected_doc_request(AccountFactory())
    res = client.post(_url(vr), _body(doc), content_type="application/json")
    assert res.status_code == 401


@pytest.mark.django_db
def test_owner_replaces_a_rejected_file_superseding_the_old_row(client):
    owner = AccountFactory()
    vr, old = _rejected_doc_request(owner)
    res = client.post(_url(vr), _body(old), content_type="application/json", **_hdr(owner))
    assert res.status_code == 201
    new = VerificationDocument.objects.get(document_id=res.json()["document_id"])
    old.refresh_from_db(); vr.refresh_from_db()
    # the replacement is a fresh pending file
    assert new.status == "pending" and new.file_url == "https://example.invalid/new"
    # the old row is SUPERSEDED but kept for the audit trail, still rejected — never mutated away
    assert old.superseded_by_id == new.document_id
    assert old.status == "rejected"
    # the request is cleared back into the queue
    assert vr.status == "pending"


@pytest.mark.django_db
def test_a_non_owner_cannot_resubmit(client):
    owner, intruder = AccountFactory(), AccountFactory()
    vr, old = _rejected_doc_request(owner)
    res = client.post(_url(vr), _body(old), content_type="application/json", **_hdr(intruder))
    assert res.status_code == 403


@pytest.mark.django_db
def test_replacing_a_non_rejected_file_is_refused(client):
    # the guard that stops this becoming a way to swap an approved ID after the fact
    owner = AccountFactory()
    vr = VerificationRequest.objects.create(account=owner, type="shelter_org", status="pending")
    approved = VerificationDocument.objects.create(verification=vr, doc_type="gov_id",
                                                   file_url="https://example.invalid/id", status="approved")
    res = client.post(_url(vr), _body(approved), content_type="application/json", **_hdr(owner))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_replaceable"
    approved.refresh_from_db()
    assert approved.superseded_by_id is None  # untouched


@pytest.mark.django_db
def test_cannot_replace_a_document_from_another_request(client):
    owner = AccountFactory()
    vr, _ = _rejected_doc_request(owner)
    other = VerificationRequest.objects.create(account=owner, type="rescuer")
    stray = VerificationDocument.objects.create(verification=other, doc_type="gov_id",
                                                file_url="https://example.invalid/s", status="rejected")
    res = client.post(_url(vr), _body(stray), content_type="application/json", **_hdr(owner))
    assert res.status_code == 404
