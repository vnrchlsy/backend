"""US-D2 · POST /media/presign — content-type/purpose validation (application-level,
no AWS call needed) + a full round trip against a mocked S3 bucket (moto)."""
import pytest
from django.utils import timezone
from moto import mock_aws

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _acc():
    return AccountFactory(email_verified_at=timezone.now())


@pytest.mark.django_db
def test_dev_stub_when_no_bucket_configured(client):
    res = client.post("/api/v1/media/presign",
                      {"purpose": "listing_photo", "content_type": "image/jpeg"},
                      content_type="application/json", **_hdr(_acc()))
    assert res.status_code == 200
    body = res.json()
    assert body["file_url"].startswith("https://example.invalid/listing_photo/")
    assert body["fields"] == {}


@pytest.mark.django_db
def test_unknown_purpose_is_422(client):
    res = client.post("/api/v1/media/presign",
                      {"purpose": "carrier_pigeon", "content_type": "image/jpeg"},
                      content_type="application/json", **_hdr(_acc()))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "purpose_unknown"


@pytest.mark.django_db
def test_disallowed_content_type_for_a_public_purpose_is_422(client):
    res = client.post("/api/v1/media/presign",
                      {"purpose": "listing_photo", "content_type": "application/pdf"},
                      content_type="application/json", **_hdr(_acc()))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "bad_content_type"


@pytest.mark.django_db
def test_pdf_is_allowed_for_verification_doc(client):
    res = client.post("/api/v1/media/presign",
                      {"purpose": "verification_doc", "content_type": "application/pdf"},
                      content_type="application/json", **_hdr(_acc()))
    assert res.status_code == 200


@pytest.mark.django_db
def test_the_key_is_server_chosen_scoped_to_purpose_and_account_never_client_supplied(client):
    acc = _acc()
    res = client.post("/api/v1/media/presign",
                      {"purpose": "stray_photo", "content_type": "image/jpeg",
                       "key": "../../someone-elses-file"},  # a client-supplied key is ignored
                      content_type="application/json", **_hdr(acc))
    file_url = res.json()["file_url"]
    assert f"stray_photo/{acc.pk}/" in file_url
    assert "someone-elses-file" not in file_url


@pytest.mark.django_db
def test_guest_is_refused(client):
    res = client.post("/api/v1/media/presign",
                      {"purpose": "listing_photo", "content_type": "image/jpeg"},
                      content_type="application/json")
    assert res.status_code == 401


@pytest.mark.django_db
def test_round_trip_against_a_mocked_s3_bucket(client, settings):
    """The full US-D2 contract, proven against a mock rather than shape-checked: a
    presigned POST that a real client can actually use to land bytes in the (mocked)
    bucket, at the server-chosen key, honoring the declared content-type."""
    import boto3
    import requests

    settings.MEDIA_S3_BUCKET_PUBLIC = "kupkop-media-public-test"
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket=settings.MEDIA_S3_BUCKET_PUBLIC)

        acc = _acc()
        res = client.post("/api/v1/media/presign",
                          {"purpose": "listing_photo", "content_type": "image/jpeg"},
                          content_type="application/json", **_hdr(acc))
        assert res.status_code == 200
        body = res.json()
        assert body["upload_url"]
        assert body["fields"]["Content-Type"] == "image/jpeg"
        key = body["fields"]["key"]
        assert key.startswith(f"listing_photo/{acc.pk}/")

        upload = requests.post(
            body["upload_url"], data=body["fields"],
            files={"file": ("photo.jpg", b"\xff\xd8\xff fake jpeg bytes", "image/jpeg")})
        assert upload.status_code in (200, 201, 204)

        head = boto3.client("s3", region_name="us-east-1").head_object(
            Bucket=settings.MEDIA_S3_BUCKET_PUBLIC, Key=key)
        assert head["ContentLength"] > 0
