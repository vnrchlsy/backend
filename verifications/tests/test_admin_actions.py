import pytest
from django.test import Client

from accounts.factories import AccountFactory
from accounts.models import StaffProfile
from verifications.models import AccountCapability, VerificationRequest

CHANGELIST = "/admin/verifications/verificationrequest/"


@pytest.fixture
def staff_reviewer(db, django_user_model):
    """A logged-in reviewer: a Django superuser linked to an admin Account (Option A)."""
    user = django_user_model.objects.create_superuser("rev", "rev@kupkop.ph", "pw")
    account = AccountFactory(account_type="admin", email="rev@kupkop.ph")
    StaffProfile.objects.create(user=user, account=account)
    client = Client()
    client.force_login(user)
    return client, account


@pytest.mark.django_db
def test_approve_action_approves_and_stamps_acting_reviewer(staff_reviewer):
    client, reviewer_account = staff_reviewer
    vr = VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")
    res = client.post(CHANGELIST, {"action": "approve_selected",
                                   "_selected_action": [str(vr.pk)]}, follow=True)
    assert res.status_code == 200
    vr.refresh_from_db()
    assert vr.status == "approved"
    assert vr.reviewed_by == reviewer_account


@pytest.mark.django_db
def test_approve_action_grants_rescuer_capability(staff_reviewer):
    client, _ = staff_reviewer
    applicant = AccountFactory()
    vr = VerificationRequest.objects.create(account=applicant, type="rescuer")
    AccountCapability.objects.create(account=applicant, capability="rescuer", status="pending")
    client.post(CHANGELIST, {"action": "approve_selected",
                             "_selected_action": [str(vr.pk)]}, follow=True)
    cap = AccountCapability.objects.get(account=applicant, capability="rescuer")
    assert cap.status == "approved" and cap.granted_at is not None


@pytest.mark.django_db
def test_reject_action_collects_a_note_then_rejects(staff_reviewer):
    client, reviewer_account = staff_reviewer
    vr = VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")
    # step 1: choosing reject renders the note page, doesn't decide yet
    page = client.post(CHANGELIST, {"action": "reject_selected",
                                    "_selected_action": [str(vr.pk)]})
    assert page.status_code == 200
    assert b"notes" in page.content.lower()
    vr.refresh_from_db()
    assert vr.status == "pending"
    # step 2: submitting the note applies the rejection
    res = client.post(CHANGELIST, {"action": "reject_selected",
                                   "_selected_action": [str(vr.pk)],
                                   "apply": "1", "notes": "Address photo is too dark to read."},
                      follow=True)
    assert res.status_code == 200
    vr.refresh_from_db()
    assert vr.status == "rejected"
    assert vr.notes == "Address photo is too dark to read."
    assert vr.reviewed_by == reviewer_account


@pytest.mark.django_db
def test_reject_action_refuses_an_empty_note(staff_reviewer):
    client, _ = staff_reviewer
    vr = VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")
    client.post(CHANGELIST, {"action": "reject_selected",
                             "_selected_action": [str(vr.pk)],
                             "apply": "1", "notes": "   "}, follow=True)
    vr.refresh_from_db()
    assert vr.status == "pending"  # a reason-less rejection is refused


@pytest.mark.django_db
def test_action_refuses_when_staffer_has_no_admin_account(db, django_user_model):
    # A superuser with no StaffProfile can't attribute a decision — it must not go through
    # anonymously (US-R5: "the decision is never anonymous").
    user = django_user_model.objects.create_superuser("nolink", "nolink@kupkop.ph", "pw")
    client = Client()
    client.force_login(user)
    vr = VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")
    client.post(CHANGELIST, {"action": "approve_selected",
                             "_selected_action": [str(vr.pk)]}, follow=True)
    vr.refresh_from_db()
    assert vr.status == "pending"
