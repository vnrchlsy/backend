"""US-K3 — GET /me/rescues: the claimer's own cases, newest claim first."""
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from sagip.models import RescueCase, StrayReport


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _report(**kw):
    defaults = dict(species="dog", condition="injured", city="Marikina",
                    geom=Point(121.05, 14.63, srid=4326))
    defaults.update(kw)
    return StrayReport.objects.create(**defaults)


@pytest.mark.django_db
def test_only_the_callers_own_cases_come_back(client):
    me, someone_else = AccountFactory(), AccountFactory()
    mine = RescueCase.objects.create(report=_report(status="claimed"), claimed_by_account=me)
    RescueCase.objects.create(report=_report(status="claimed"), claimed_by_account=someone_else)

    res = client.get("/api/v1/me/rescues", **_hdr(me))
    cases = res.json()["cases"]
    assert [c["case_id"] for c in cases] == [str(mine.pk)]


@pytest.mark.django_db
def test_newest_claim_comes_first(client):
    me = AccountFactory()
    older = RescueCase.objects.create(report=_report(status="claimed"), claimed_by_account=me)
    newer = RescueCase.objects.create(report=_report(status="claimed"), claimed_by_account=me)
    # auto_now_add on claimed_at means insertion order already reflects time, but force
    # the ordering explicitly rather than relying on clock resolution between two creates.
    RescueCase.objects.filter(pk=older.pk).update(
        claimed_at=timezone.now() - timezone.timedelta(hours=1))

    res = client.get("/api/v1/me/rescues", **_hdr(me))
    ids = [c["case_id"] for c in res.json()["cases"]]
    assert ids == [str(newer.pk), str(older.pk)]


@pytest.mark.django_db
def test_active_resolved_and_expired_cases_all_come_back(client):
    me = AccountFactory()
    active = RescueCase.objects.create(report=_report(status="claimed"), claimed_by_account=me)
    resolved = RescueCase.objects.create(
        report=_report(status="resolved"), claimed_by_account=me, resolved_at=timezone.now())
    expired = RescueCase.objects.create(
        report=_report(status="reported"), claimed_by_account=me, expired_at=timezone.now())

    res = client.get("/api/v1/me/rescues", **_hdr(me))
    by_id = {c["case_id"]: c for c in res.json()["cases"]}
    assert set(by_id) == {str(active.pk), str(resolved.pk), str(expired.pk)}
    assert by_id[str(active.pk)]["expired_at"] is None
    assert by_id[str(expired.pk)]["expired_at"] is not None


@pytest.mark.django_db
def test_the_status_reflects_the_report_not_a_stored_case_field(client):
    me = AccountFactory()
    case = RescueCase.objects.create(report=_report(status="safe"), claimed_by_account=me)

    res = client.get("/api/v1/me/rescues", **_hdr(me))
    row = res.json()["cases"][0]
    assert row["status"] == "safe"
    assert row["report"] == {"species": "dog", "condition": "injured", "city": "Marikina"}
    assert case.pk  # sanity: the fixture case actually exists


@pytest.mark.django_db
def test_a_guest_is_401d(client):
    res = client.get("/api/v1/me/rescues")
    assert res.status_code == 401
