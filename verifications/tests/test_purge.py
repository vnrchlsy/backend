"""US-SEC4 — the 90-day identity-document retention purge."""
import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from verifications.models import VerificationDocument, VerificationRequest
from verifications.purge import purge_expired_documents


def _terminal_request(status="approved", days_since_decision=91):
    return VerificationRequest.objects.create(
        account=AccountFactory(), type="shelter_org", status=status,
        reviewed_at=timezone.now() - timezone.timedelta(days=days_since_decision))


def _doc(vr, file_url="https://example.invalid/gov_id.jpg", **extra):
    return VerificationDocument.objects.create(verification=vr, doc_type="gov_id",
                                               file_url=file_url, **extra)


@pytest.mark.django_db
def test_purges_a_document_past_the_retention_window():
    vr = _terminal_request(days_since_decision=91)
    doc = _doc(vr)

    purged = purge_expired_documents()

    doc.refresh_from_db()
    assert doc in purged
    assert doc.file_url == ""
    assert doc.purged_at is not None


@pytest.mark.django_db
def test_does_not_purge_before_the_90_day_window():
    vr = _terminal_request(days_since_decision=89)
    doc = _doc(vr)

    purged = purge_expired_documents()

    doc.refresh_from_db()
    assert purged == []
    assert doc.file_url != ""
    assert doc.purged_at is None


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["pending", "needs_info"])
def test_does_not_purge_a_non_terminal_request_even_if_old(status):
    vr = VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org",
                                            status=status)
    doc = _doc(vr)

    purged = purge_expired_documents()

    doc.refresh_from_db()
    assert purged == []
    assert doc.file_url != ""


@pytest.mark.django_db
def test_is_idempotent():
    vr = _terminal_request(days_since_decision=100)
    _doc(vr)

    first = purge_expired_documents()
    second = purge_expired_documents()

    assert len(first) == 1
    assert second == []


@pytest.mark.django_db
def test_calls_delete_object_with_the_original_url_before_nulling(monkeypatch):
    calls = []
    monkeypatch.setattr("verifications.purge.delete_object", lambda url: calls.append(url))
    vr = _terminal_request(days_since_decision=91)
    _doc(vr, file_url="https://example.invalid/gov_id.jpg")

    purge_expired_documents()

    assert calls == ["https://example.invalid/gov_id.jpg"]


@pytest.mark.django_db
def test_a_superseded_document_purges_alongside_the_request_it_belongs_to():
    vr = _terminal_request(status="rejected", days_since_decision=91)
    replacement = _doc(vr, file_url="https://example.invalid/replacement.jpg")
    rejected = _doc(vr, file_url="https://example.invalid/original.jpg",
                    superseded_by=replacement)

    purge_expired_documents()

    rejected.refresh_from_db()
    replacement.refresh_from_db()
    assert rejected.file_url == ""
    assert replacement.file_url == ""


@pytest.mark.django_db
def test_verification_request_row_and_decision_survive_the_purge():
    vr = _terminal_request(days_since_decision=91)
    _doc(vr)

    purge_expired_documents()

    vr.refresh_from_db()
    assert vr.status == "approved"
    assert vr.reviewed_at is not None
