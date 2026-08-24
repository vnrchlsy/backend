"""Access-restricted media signing seam (US-R3).

Verification documents live in a private bucket; the reviewer sees them via **short-lived
signed GET URLs**, never a public link. Every render path goes through `signed_get_url`,
so the day a real S3 bucket is configured only this function changes — nothing emits a raw
object URL directly.

This is the same dev-stub pattern the OTP sender and social-auth seam use: with no bucket
configured (the current dev slice, where `POST /media/presign` returns
`https://example.invalid/...` placeholders), signing degrades to returning the stored
reference so review still renders. Media handling is finalized in Sprint 3.
"""
from django.conf import settings

# Signed URLs are minted fresh on each page render and must not outlive it.
SIGNED_URL_TTL = 300  # seconds (5 minutes)


def signed_get_url(file_url, expires_in=SIGNED_URL_TTL):
    """A short-lived signed GET URL for a stored document reference.

    Dev (no `MEDIA_S3_BUCKET`): returns `file_url` unchanged. Production signs the S3
    object with boto3 (imported lazily so the dev slice needs no AWS dependency).
    """
    bucket = getattr(settings, "MEDIA_S3_BUCKET", "")
    if not bucket:
        return file_url
    import boto3  # prod-only; not a dev dependency

    key = file_url.split(f"{bucket}/", 1)[-1]
    return boto3.client("s3").generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_in)


def delete_object(file_url):
    """Delete the stored object backing `file_url` (US-SEC4 retention purge).

    Same dev-stub seam as `signed_get_url`: no bucket configured means no real object
    ever existed behind the `https://example.invalid/...` placeholder, so this is a
    no-op today. Once US-D2 wires a real bucket, this is the one place that starts
    issuing real deletes — `purge_expired_documents` itself doesn't change.
    """
    bucket = getattr(settings, "MEDIA_S3_BUCKET", "")
    if not bucket:
        return
    import boto3  # prod-only; not a dev dependency

    key = file_url.split(f"{bucket}/", 1)[-1]
    boto3.client("s3").delete_object(Bucket=bucket, Key=key)
