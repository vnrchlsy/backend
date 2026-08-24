import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from volunteer.models import SignupStatus, VolunteerShift, VolunteerSignup


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _signup(hours_out=-3, status=SignupStatus.APPROVED):
    """Negative hours_out = the shift already happened."""
    shift = VolunteerShift.objects.create(
        shelter_account=AccountFactory(account_type="shelter"),
        starts_at=timezone.now() + timezone.timedelta(hours=hours_out),
        ends_at=timezone.now() + timezone.timedelta(hours=hours_out + 2), capacity=2)
    su = VolunteerSignup.objects.create(shift=shift, volunteer_account=AccountFactory(),
                                        status=status, waiver_accepted=True)
    return shift, su


@pytest.mark.django_db
def test_check_in_then_out(client):
    shift, su = _signup()
    assert client.post(f"/api/v1/signups/{su.pk}/check-in",
                       **_hdr(su.volunteer_account)).status_code == 200
    assert client.post(f"/api/v1/signups/{su.pk}/check-out",
                       **_hdr(su.volunteer_account)).status_code == 200
    su.refresh_from_db()
    assert su.check_in_at is not None and su.check_out_at is not None


@pytest.mark.django_db
def test_only_an_approved_signup_can_check_in(client):
    shift, su = _signup(status=SignupStatus.REQUESTED)
    res = client.post(f"/api/v1/signups/{su.pk}/check-in", **_hdr(su.volunteer_account))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_approved"


@pytest.mark.django_db
def test_shelter_marks_attended(client):
    shift, su = _signup()
    res = client.post(f"/api/v1/shelter/signups/{su.pk}/attendance",
                      {"outcome": "completed"}, content_type="application/json",
                      **_hdr(shift.shelter_account))
    assert res.status_code == 200
    su.refresh_from_db()
    assert su.status == SignupStatus.COMPLETED


@pytest.mark.django_db
def test_shelter_marks_no_show(client):
    shift, su = _signup()
    client.post(f"/api/v1/shelter/signups/{su.pk}/attendance", {"outcome": "no_show"},
                content_type="application/json", **_hdr(shift.shelter_account))
    su.refresh_from_db()
    assert su.status == SignupStatus.NO_SHOW


@pytest.mark.django_db
def test_attendance_cannot_be_marked_before_the_shift_ends(client):
    shift, su = _signup(hours_out=+5)      # still in the future
    res = client.post(f"/api/v1/shelter/signups/{su.pk}/attendance",
                      {"outcome": "completed"}, content_type="application/json",
                      **_hdr(shift.shelter_account))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "shift_not_ended"


@pytest.mark.django_db
def test_another_shelter_cannot_mark_attendance(client):
    shift, su = _signup()
    res = client.post(f"/api/v1/shelter/signups/{su.pk}/attendance",
                      {"outcome": "completed"}, content_type="application/json",
                      **_hdr(AccountFactory(account_type="shelter")))
    assert res.status_code == 403
