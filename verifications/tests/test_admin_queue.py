import datetime

import pytest
from django.contrib import admin as django_admin
from django.utils import timezone

from accounts.factories import AccountFactory
from shelter.models import ShelterProfile
from verifications.models import VerificationRequest


def _queue_admin():
    return django_admin.site._registry[VerificationRequest]


@pytest.mark.django_db
def test_verification_request_registered_in_admin():
    assert VerificationRequest in django_admin.site._registry


@pytest.mark.django_db
def test_queue_has_status_and_type_filters_and_expected_columns():
    ma = _queue_admin()
    assert set(ma.list_filter) >= {"status", "type"}
    for col in ("applicant", "type", "tier", "submitted_at", "status"):
        assert col in ma.list_display


@pytest.mark.django_db
def test_tier_resolves_for_shelter_org_and_dashes_for_rescuer():
    ma = _queue_admin()
    shelter_acc = AccountFactory(account_type="shelter")
    profile = ShelterProfile.objects.create(account=shelter_acc, org_name="Pasig Rescue",
                                             org_type="rescue", tier="registered_ngo")
    org_req = VerificationRequest.objects.create(account=shelter_acc, type="shelter_org")
    # a shelter_org request shows the applicant's own tier (drives the required-doc set)
    assert ma.tier(org_req) == profile.get_tier_display()
    assert ma.tier(org_req) != "—"

    member_acc = AccountFactory(account_type="personal")
    rescuer_req = VerificationRequest.objects.create(account=member_acc, type="rescuer")
    # a Verified Member has no shelter profile → the dash sentinel, never a blank
    assert ma.tier(rescuer_req) == "—"


@pytest.mark.django_db
def test_queue_orders_pending_oldest_first_then_decided(admin_client):
    now = timezone.now()

    def mk(status, days_ago):
        acc = AccountFactory()
        r = VerificationRequest.objects.create(account=acc, type="shelter_org")
        # submitted_at is auto_now_add; a queryset .update() bypasses it so the test can
        # place rows deterministically in time.
        VerificationRequest.objects.filter(pk=r.pk).update(
            status=status, submitted_at=now - datetime.timedelta(days=days_ago))
        return r.pk

    old_pending = mk("pending", 3)
    new_pending = mk("pending", 1)
    older_approved = mk("approved", 4)  # oldest overall, but already decided → sorts last

    res = admin_client.get("/admin/verifications/verificationrequest/")
    assert res.status_code == 200
    order = [obj.pk for obj in res.context["cl"].result_list]
    assert order == [old_pending, new_pending, older_approved]


@pytest.mark.django_db
def test_queue_is_read_only_no_add(admin_client):
    # Requests come from applicants via the API; the queue must not offer an "add" form.
    res = admin_client.get("/admin/verifications/verificationrequest/add/")
    assert res.status_code == 403


@pytest.mark.django_db
def test_queue_is_read_only_no_delete(admin_client):
    # A verification request is the audit trail of a trust decision; the reviewer surface
    # must not be able to delete one.
    acc = AccountFactory()
    r = VerificationRequest.objects.create(account=acc, type="shelter_org")
    res = admin_client.get(f"/admin/verifications/verificationrequest/{r.pk}/delete/")
    assert res.status_code == 403


@pytest.mark.django_db
def test_non_staff_cannot_view_queue(client, django_user_model):
    user = django_user_model.objects.create_user("bob", password="irrelevant")
    client.force_login(user)
    res = client.get("/admin/verifications/verificationrequest/")
    assert res.status_code == 302
    assert "/admin/login/" in res.headers["Location"]
