"""US-R3 — see every document at once, via short-lived signed URLs, rescue_photos grouped."""
import pytest

from accounts.factories import AccountFactory
from verifications.models import VerificationDocument, VerificationRequest

CHANGE = "/admin/verifications/verificationrequest/{}/change/"


def _docs(vr, specs):
    for doc_type, status in specs:
        VerificationDocument.objects.create(
            verification=vr, doc_type=doc_type, status=status,
            file_url=f"https://example.invalid/{doc_type}-{status}")


def _request():
    return VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")


@pytest.mark.django_db
def test_preview_shows_each_document_labelled_with_type_and_status(admin_client):
    vr = _request()
    _docs(vr, [("gov_id", "approved"), ("proof_billing", "rejected")])
    content = admin_client.get(CHANGE.format(vr.pk)).content.decode()
    assert "gov_id" in content and "approved" in content
    assert "proof_billing" in content and "rejected" in content


@pytest.mark.django_db
def test_rescue_photos_render_as_one_group_not_four_rows(admin_client):
    vr = _request()
    _docs(vr, [("rescue_photos", "pending")] * 3)
    content = admin_client.get(CHANGE.format(vr.pk)).content.decode()
    # a single grouped label with a count — not three identical rows
    assert "rescue_photos (3)" in content


@pytest.mark.django_db
def test_preview_renders_via_the_signing_seam_never_a_raw_url(admin_client, monkeypatch):
    monkeypatch.setattr("verifications.admin.signed_get_url", lambda u, **k: "SIGNED://token")
    vr = _request()
    _docs(vr, [("gov_id", "pending")])
    content = admin_client.get(CHANGE.format(vr.pk)).content.decode()
    assert "SIGNED://token" in content
    # the raw stored reference must never be emitted to the page
    assert "example.invalid/gov_id-pending" not in content
