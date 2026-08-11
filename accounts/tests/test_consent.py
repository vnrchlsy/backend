"""US-A1 · the signup Terms/Privacy consent must be RECORDED, not just rendered.

RA 10173 puts the burden on the controller to demonstrate consent was obtained. The
signup screen has carried the line since Sprint 1, but nothing persisted it until the
2026-08-06 audit caught it (dev/sprint-1-stories.md).
"""
import pytest
from django.test import override_settings

from accounts.models import Account


@pytest.mark.django_db
def test_signup_records_consent_timestamp_and_version(client):
    res = client.post("/api/v1/auth/signup", {
        "account_type": "personal", "display_name": "Ana",
        "email": "ana@example.com", "password": "s3cretpass",
        "consent_version": "2026-08-01",
    }, content_type="application/json")
    assert res.status_code == 201
    acc = Account.objects.get(email="ana@example.com")
    assert acc.terms_consent_at is not None
    assert acc.terms_consent_version == "2026-08-01"


@pytest.mark.django_db
@override_settings(TERMS_VERSION="2026-08-01")
def test_signup_from_an_older_client_still_records_consent(client):
    """An older build that doesn't send consent_version must still produce a record —
    falling back to the server's current terms version rather than storing nothing."""
    res = client.post("/api/v1/auth/signup", {
        "account_type": "personal", "display_name": "Ben",
        "email": "ben@example.com", "password": "s3cretpass",
    }, content_type="application/json")
    assert res.status_code == 201
    acc = Account.objects.get(email="ben@example.com")
    assert acc.terms_consent_at is not None
    assert acc.terms_consent_version == "2026-08-01"


@pytest.mark.django_db
def test_social_signup_also_records_consent(client, monkeypatch):
    """The social path creates accounts too — it must not be a hole in the record."""
    monkeypatch.setattr("accounts.social.verify_token",
                        lambda provider, id_token: {"sub": "g-1", "email": "cara@example.com"})
    res = client.post("/api/v1/auth/social/google",
                      {"id_token": "x", "account_type": "personal"},
                      content_type="application/json")
    assert res.status_code == 200
    acc = Account.objects.get(email="cara@example.com")
    assert acc.terms_consent_at is not None, "social signup left no consent record"


@pytest.mark.django_db
def test_document_consent_is_a_separate_record(client):
    """account.terms_consent_* (account creation) and verification_request.consent_*
    (identity-document collection, §12.6) are different consents. Signing up must not
    imply consent to hand over a government ID."""
    client.post("/api/v1/auth/signup", {
        "account_type": "personal", "display_name": "Dee",
        "email": "dee@example.com", "password": "s3cretpass",
        "consent_version": "2026-08-01",
    }, content_type="application/json")
    acc = Account.objects.get(email="dee@example.com")
    assert acc.terms_consent_at is not None
    assert not acc.verifications.exists(), "signup must not create a document-consent record"
