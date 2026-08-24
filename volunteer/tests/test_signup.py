import pytest
from django.conf import settings
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from notifications.models import Notification
from volunteer.models import ShiftStatus, SignupStatus, VolunteerShift, VolunteerSignup


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _shift(**kw):
    defaults = dict(shelter_account=AccountFactory(account_type="shelter"),
                    starts_at=timezone.now() + timezone.timedelta(days=2),
                    ends_at=timezone.now() + timezone.timedelta(days=2, hours=2), capacity=2)
    defaults.update(kw)
    return VolunteerShift.objects.create(**defaults)


def _body(**kw):
    d = {"waiver_accepted": True, "contact_share_consent": True}
    d.update(kw)
    return d


@pytest.mark.django_db
def test_browse_is_public(client):
    _shift()
    res = client.get("/api/v1/shifts")
    assert res.status_code == 200
    assert len(res.json()["results"]) == 1


@pytest.mark.django_db
def test_browse_hides_closed_shifts(client):
    _shift(status=ShiftStatus.CLOSED)
    assert client.get("/api/v1/shifts").json()["results"] == []


@pytest.mark.django_db
def test_browse_includes_full_shifts_as_slots_left_zero(client):
    s = _shift(status=ShiftStatus.FULL, capacity=1)
    VolunteerSignup.objects.create(shift=s, volunteer_account=AccountFactory(),
                                   status=SignupStatus.APPROVED)
    results = client.get("/api/v1/shifts").json()["results"]
    assert str(s.pk) in [r["shift_id"] for r in results]
    full = next(r for r in results if r["shift_id"] == str(s.pk))
    assert full["slots_left"] == 0


@pytest.mark.django_db
def test_detail_reports_slots_left(client):
    s = _shift(capacity=3)
    VolunteerSignup.objects.create(shift=s, volunteer_account=AccountFactory(),
                                   status=SignupStatus.APPROVED)
    assert client.get(f"/api/v1/shifts/{s.pk}").json()["slots_left"] == 2


@pytest.mark.django_db
def test_request_creates_a_requested_signup_and_notifies_the_shelter(client):
    s = _shift()
    vol = AccountFactory()
    res = client.post(f"/api/v1/shifts/{s.pk}/signups", _body(),
                      content_type="application/json", **_hdr(vol))
    assert res.status_code == 201
    assert res.json()["status"] == "requested"
    assert Notification.objects.filter(account=s.shelter_account,
                                       type="signup_requested").count() == 1


@pytest.mark.django_db
def test_both_consents_are_stamped_and_the_waiver_is_versioned(client):
    s = _shift()
    vol = AccountFactory()
    client.post(f"/api/v1/shifts/{s.pk}/signups", _body(),
                content_type="application/json", **_hdr(vol))
    su = VolunteerSignup.objects.get(shift=s, volunteer_account=vol)
    assert su.waiver_accepted is True
    assert su.waiver_accepted_at is not None
    assert su.waiver_version == settings.WAIVER_VERSION
    assert su.contact_share_consent is True
    assert su.contact_share_consent_at is not None


@pytest.mark.django_db
def test_declining_contact_sharing_still_allows_the_request(client):
    """The waiver is required; contact-sharing is optional and separate."""
    s = _shift()
    vol = AccountFactory()
    res = client.post(f"/api/v1/shifts/{s.pk}/signups", _body(contact_share_consent=False),
                      content_type="application/json", **_hdr(vol))
    assert res.status_code == 201
    su = VolunteerSignup.objects.get(shift=s, volunteer_account=vol)
    assert su.contact_share_consent is False
    assert su.contact_share_consent_at is None


@pytest.mark.django_db
def test_the_waiver_is_required(client):
    s = _shift()
    res = client.post(f"/api/v1/shifts/{s.pk}/signups", _body(waiver_accepted=False),
                      content_type="application/json", **_hdr(AccountFactory()))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "waiver_required"


@pytest.mark.django_db
def test_requesting_twice_is_409_not_500(client):
    s = _shift()
    vol = AccountFactory()
    client.post(f"/api/v1/shifts/{s.pk}/signups", _body(),
                content_type="application/json", **_hdr(vol))
    res = client.post(f"/api/v1/shifts/{s.pk}/signups", _body(),
                      content_type="application/json", **_hdr(vol))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "already_requested"


@pytest.mark.django_db
def test_cannot_request_a_closed_shift(client):
    s = _shift(status=ShiftStatus.CLOSED)
    res = client.post(f"/api/v1/shifts/{s.pk}/signups", _body(),
                      content_type="application/json", **_hdr(AccountFactory()))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "shift_not_open"


@pytest.mark.django_db
def test_guest_cannot_request(client):
    s = _shift()
    res = client.post(f"/api/v1/shifts/{s.pk}/signups", _body(),
                      content_type="application/json")
    assert res.status_code == 401
