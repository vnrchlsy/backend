import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from volunteer.models import ShiftStatus, SignupStatus, VolunteerShift, VolunteerSignup


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _booked(hours_out, capacity=1, status=SignupStatus.APPROVED):
    shift = VolunteerShift.objects.create(
        shelter_account=AccountFactory(account_type="shelter"),
        starts_at=timezone.now() + timezone.timedelta(hours=hours_out),
        ends_at=timezone.now() + timezone.timedelta(hours=hours_out + 2),
        capacity=capacity,
        status=ShiftStatus.FULL if capacity == 1 else ShiftStatus.OPEN)
    su = VolunteerSignup.objects.create(shift=shift, volunteer_account=AccountFactory(),
                                        status=status, waiver_accepted=True)
    return shift, su


@pytest.mark.django_db
def test_cancelling_well_ahead_is_free(client):
    shift, su = _booked(hours_out=48)
    res = client.post(f"/api/v1/signups/{su.pk}/cancel", **_hdr(su.volunteer_account))
    assert res.status_code == 200
    assert res.json()["was_late"] is False


@pytest.mark.django_db
def test_cancelling_inside_the_cutoff_is_recorded_as_late(client):
    shift, su = _booked(hours_out=3)
    res = client.post(f"/api/v1/signups/{su.pk}/cancel", **_hdr(su.volunteer_account))
    assert res.status_code == 200
    assert res.json()["was_late"] is True


@pytest.mark.django_db
def test_the_boundary_is_not_late(client):
    """Exactly at the cutoff is still free — 'free up to 12h before'."""
    shift, su = _booked(hours_out=13)
    assert client.post(f"/api/v1/signups/{su.pk}/cancel",
                       **_hdr(su.volunteer_account)).json()["was_late"] is False


@pytest.mark.django_db
def test_cancel_stamps_cancelled_at_and_releases_capacity(client):
    shift, su = _booked(hours_out=48, capacity=1)
    client.post(f"/api/v1/signups/{su.pk}/cancel", **_hdr(su.volunteer_account))
    su.refresh_from_db()
    shift.refresh_from_db()
    assert su.status == SignupStatus.CANCELLED
    assert su.cancelled_at is not None
    assert shift.status == ShiftStatus.OPEN, "capacity must re-open"


@pytest.mark.django_db
def test_only_the_volunteer_can_cancel_their_own_signup(client):
    shift, su = _booked(hours_out=48)
    res = client.post(f"/api/v1/signups/{su.pk}/cancel", **_hdr(AccountFactory()))
    assert res.status_code == 403


@pytest.mark.django_db
def test_a_terminal_signup_cannot_be_cancelled(client):
    shift, su = _booked(hours_out=48, status=SignupStatus.COMPLETED)
    res = client.post(f"/api/v1/signups/{su.pk}/cancel", **_hdr(su.volunteer_account))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_cancellable"


@pytest.mark.django_db
def test_lateness_is_computed_server_side_not_taken_from_the_client(client):
    """A client that claims it is early must not get a free cancel."""
    shift, su = _booked(hours_out=2)
    res = client.post(f"/api/v1/signups/{su.pk}/cancel", {"was_late": False},
                      content_type="application/json", **_hdr(su.volunteer_account))
    assert res.json()["was_late"] is True
