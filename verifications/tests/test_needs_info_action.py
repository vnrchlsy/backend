"""US-R6 admin flow — reject one file with a per-file note and bounce the request."""
import pytest
from django.test import Client
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.factories import AccountFactory
from accounts.models import StaffProfile
from verifications.models import VerificationDocument, VerificationRequest

CHANGELIST = "/admin/verifications/verificationrequest/"


@pytest.fixture
def staff_reviewer(db, django_user_model):
    user = django_user_model.objects.create_superuser("rev", "rev@kupkop.ph", "pw")
    account = AccountFactory(account_type="admin", email="rev@kupkop.ph")
    StaffProfile.objects.create(user=user, account=account)
    client = Client()
    client.force_login(user)
    # US-SEC3 · the admin now gates on a verified TOTP device, not just is_staff.
    device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    return client, account


def _request_with_two_docs():
    vr = VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")
    gov = VerificationDocument.objects.create(verification=vr, doc_type="gov_id",
                                              file_url="https://example.invalid/gov")
    billing = VerificationDocument.objects.create(verification=vr, doc_type="proof_billing",
                                                  file_url="https://example.invalid/bill")
    return vr, gov, billing


@pytest.mark.django_db
def test_intermediate_page_lists_the_documents(staff_reviewer):
    client, _ = staff_reviewer
    vr, _, _ = _request_with_two_docs()
    page = client.post(CHANGELIST, {"action": "needs_info",
                                    "_selected_action": [str(vr.pk)]})
    assert page.status_code == 200
    body = page.content.decode()
    assert "gov_id" in body and "proof_billing" in body


@pytest.mark.django_db
def test_rejects_only_the_named_file_and_bounces_the_request(staff_reviewer):
    client, reviewer_account = staff_reviewer
    vr, gov, billing = _request_with_two_docs()
    client.post(CHANGELIST, {
        "action": "needs_info", "_selected_action": [str(vr.pk)], "apply": "1",
        f"reject_{billing.pk}": "on", f"note_{billing.pk}": "Too dark to read the address.",
        "notes": "Please replace the billing photo.",
    }, follow=True)
    gov.refresh_from_db(); billing.refresh_from_db(); vr.refresh_from_db()
    # only the billing file was bounced, with its per-file reason
    assert billing.status == "rejected"
    assert billing.review_note == "Too dark to read the address."
    assert billing.reviewed_by == reviewer_account
    # the cleared file is untouched
    assert gov.status == "pending"
    # the request is back with the applicant
    assert vr.status == "needs_info"
    assert vr.notes == "Please replace the billing photo."


@pytest.mark.django_db
def test_overall_note_is_required(staff_reviewer):
    client, _ = staff_reviewer
    vr, _, billing = _request_with_two_docs()
    client.post(CHANGELIST, {
        "action": "needs_info", "_selected_action": [str(vr.pk)], "apply": "1",
        f"reject_{billing.pk}": "on", f"note_{billing.pk}": "Too dark.", "notes": "   ",
    }, follow=True)
    vr.refresh_from_db(); billing.refresh_from_db()
    # atomic: an empty overall note refuses the whole bounce — nothing applied
    assert vr.status == "pending"
    assert billing.status == "pending"


@pytest.mark.django_db
def test_rejecting_a_file_without_a_note_refuses_the_whole_bounce(staff_reviewer):
    client, _ = staff_reviewer
    vr, _, billing = _request_with_two_docs()
    client.post(CHANGELIST, {
        "action": "needs_info", "_selected_action": [str(vr.pk)], "apply": "1",
        f"reject_{billing.pk}": "on", f"note_{billing.pk}": "", "notes": "Fix it.",
    }, follow=True)
    vr.refresh_from_db(); billing.refresh_from_db()
    assert billing.status == "pending"
    assert vr.status == "pending"
