import threading

import pytest
from django.db import connection
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from notifications.models import Notification
from volunteer.models import ShiftStatus, SignupStatus, VolunteerShift, VolunteerSignup


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _shift(capacity=1, shelter=None):
    return VolunteerShift.objects.create(
        shelter_account=shelter or AccountFactory(account_type="shelter"),
        starts_at=timezone.now() + timezone.timedelta(days=2),
        ends_at=timezone.now() + timezone.timedelta(days=2, hours=2), capacity=capacity)


def _signup(shift):
    return VolunteerSignup.objects.create(shift=shift, volunteer_account=AccountFactory(),
                                          waiver_accepted=True)


@pytest.mark.django_db
def test_approve_confirms_and_notifies(client):
    shift = _shift(capacity=2)
    su = _signup(shift)
    res = client.post(f"/api/v1/shelter/signups/{su.pk}/approve", **_hdr(shift.shelter_account))
    assert res.status_code == 200
    su.refresh_from_db()
    assert su.status == SignupStatus.APPROVED
    assert Notification.objects.filter(account=su.volunteer_account,
                                       type="shift_confirmed").count() == 1


@pytest.mark.django_db
def test_the_last_approval_flips_the_shift_to_full(client):
    shift = _shift(capacity=1)
    su = _signup(shift)
    client.post(f"/api/v1/shelter/signups/{su.pk}/approve", **_hdr(shift.shelter_account))
    shift.refresh_from_db()
    assert shift.status == ShiftStatus.FULL


@pytest.mark.django_db
def test_approving_past_capacity_is_409_shift_full(client):
    shift = _shift(capacity=1)
    first, second = _signup(shift), _signup(shift)
    client.post(f"/api/v1/shelter/signups/{first.pk}/approve", **_hdr(shift.shelter_account))
    res = client.post(f"/api/v1/shelter/signups/{second.pk}/approve",
                      **_hdr(shift.shelter_account))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "shift_full"


@pytest.mark.django_db
def test_decline_notifies_so_nobody_sits_in_silent_pending(client):
    shift = _shift(capacity=2)
    su = _signup(shift)
    res = client.post(f"/api/v1/shelter/signups/{su.pk}/decline", **_hdr(shift.shelter_account))
    assert res.status_code == 200
    su.refresh_from_db()
    assert su.status == SignupStatus.DECLINED
    assert Notification.objects.filter(account=su.volunteer_account,
                                       type="signup_declined").count() == 1


@pytest.mark.django_db
def test_another_shelter_cannot_approve(client):
    shift = _shift(capacity=2)
    su = _signup(shift)
    res = client.post(f"/api/v1/shelter/signups/{su.pk}/approve",
                      **_hdr(AccountFactory(account_type="shelter")))
    assert res.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_concurrent_approvals_cannot_overfill_a_capacity_one_shift(client):
    """The reason the lock exists. Two approvals race on a capacity-1 shift; exactly one
    must win. Without select_for_update both read approved_count == 0 and both write."""
    shift = _shift(capacity=1)
    a, b = _signup(shift), _signup(shift)
    hdr = _hdr(shift.shelter_account)
    codes = []
    barrier = threading.Barrier(2)

    def approve(signup_id):
        try:
            barrier.wait(timeout=5)
            r = client.post(f"/api/v1/shelter/signups/{signup_id}/approve", **hdr)
            codes.append(r.status_code)
        finally:
            connection.close()  # each thread holds its own DB connection

    threads = [threading.Thread(target=approve, args=(s.pk,)) for s in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(codes) == [200, 409], f"expected one win and one 409, got {codes}"
    assert VolunteerSignup.objects.filter(
        shift=shift, status=SignupStatus.APPROVED).count() == 1
