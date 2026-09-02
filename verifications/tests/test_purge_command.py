"""US-SEC4 — `purge_expired_documents` runs standalone, beside `run_sweeps`."""
import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.factories import AccountFactory
from verifications.models import VerificationDocument, VerificationRequest


@pytest.mark.django_db
def test_command_reports_how_many_documents_it_purged(capsys):
    vr = VerificationRequest.objects.create(
        account=AccountFactory(), type="shelter_org", status="approved",
        reviewed_at=timezone.now() - timezone.timedelta(days=91))
    VerificationDocument.objects.create(verification=vr, doc_type="gov_id",
                                        file_url="https://example.invalid/gov_id.jpg")

    call_command("purge_expired_documents")

    out = capsys.readouterr().out
    assert "purged 1 document" in out
