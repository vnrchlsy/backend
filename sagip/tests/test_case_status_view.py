"""US-K2 — POST /cases/{id}/status: only the claimer, forward-only, resolved is terminal.

Every accepted move must go through set_report_status (so it's logged) — that log is what
keeps a worked case from looking stalled to US-E2's auto-expiry sweep, so these tests check
case_status_history alongside the HTTP response, not just the response.
"""
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from sagip.models import CaseStatusHistory, RescueCase, StrayReport


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _advance(client, case, acc, status, **extra):
    return client.post(f"/api/v1/cases/{case.pk}/status",
                       {"status": status, **extra}, content_type="application/json",
                       **_hdr(acc))


def _claimed_case():
    """A report already in `claimed` state with an active RescueCase — bypasses US-K1's
    endpoint since K2 only cares about what happens after a claim exists."""
    claimer = AccountFactory()
    report = StrayReport.objects.create(species="dog", condition="injured", status="claimed",
                                        geom=Point(121.05, 14.63, srid=4326))
    case = RescueCase.objects.create(report=report, claimed_by_account=claimer)
    return case, claimer


@pytest.mark.django_db
def test_only_the_claimer_can_advance_the_case(client):
    case, _claimer = _claimed_case()
    someone_else = AccountFactory()
    res = _advance(client, case, someone_else, "rescued")
    assert res.status_code == 403
    case.report.refresh_from_db()
    assert case.report.status == "claimed"  # untouched


@pytest.mark.django_db
def test_the_claimer_can_advance_one_step(client):
    case, claimer = _claimed_case()
    res = _advance(client, case, claimer, "rescued", note="Picked up from the roadside")
    assert res.status_code == 200
    assert res.json()["status"] == "rescued"
    case.report.refresh_from_db()
    assert case.report.status == "rescued"
    history = CaseStatusHistory.objects.get(report=case.report)
    assert history.status == "rescued" and history.note == "Picked up from the roadside"
    assert history.changed_by_account_id == claimer.pk


@pytest.mark.django_db
def test_the_claimer_can_skip_ahead_since_the_rule_is_forward_not_one_step(client):
    """The story's contract says 'forward-only', not 'one step at a time' — a case that's
    rescued and immediately safe (no separate vet stop) should be representable in one call."""
    case, claimer = _claimed_case()
    res = _advance(client, case, claimer, "safe")
    assert res.status_code == 200
    case.report.refresh_from_db()
    assert case.report.status == "safe"


@pytest.mark.django_db
def test_a_backward_move_is_rejected(client):
    case, claimer = _claimed_case()
    _advance(client, case, claimer, "safe")
    res = _advance(client, case, claimer, "rescued")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_forward"
    case.report.refresh_from_db()
    assert case.report.status == "safe"  # untouched


@pytest.mark.django_db
def test_reposting_the_current_status_is_rejected(client):
    case, claimer = _claimed_case()
    _advance(client, case, claimer, "rescued")
    res = _advance(client, case, claimer, "rescued")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_forward"


@pytest.mark.django_db
def test_resolving_captures_the_outcome_and_stamps_resolved_at(client):
    case, claimer = _claimed_case()
    res = _advance(client, case, claimer, "safe")
    assert res.status_code == 200
    res = _advance(client, case, claimer, "resolved",
                   outcome_notes="Reunited with a foster the same night",
                   outcome_photo_url="https://example.invalid/outcome.jpg")
    assert res.status_code == 200
    case.refresh_from_db()
    assert case.outcome_notes == "Reunited with a foster the same night"
    assert case.outcome_photo_url == "https://example.invalid/outcome.jpg"
    assert case.resolved_at is not None
    case.report.refresh_from_db()
    assert case.report.status == "resolved"


@pytest.mark.django_db
def test_resolved_is_terminal(client):
    case, claimer = _claimed_case()
    _advance(client, case, claimer, "safe")
    _advance(client, case, claimer, "resolved")
    res = _advance(client, case, claimer, "resolved")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "case_resolved"


@pytest.mark.django_db
def test_an_expired_case_cannot_be_advanced(client):
    case, claimer = _claimed_case()
    case.expired_at = timezone.now()
    case.save(update_fields=["expired_at"])
    res = _advance(client, case, claimer, "rescued")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "case_expired"


@pytest.mark.django_db
def test_an_invalid_target_status_is_rejected(client):
    case, claimer = _claimed_case()
    res = _advance(client, case, claimer, "reported")  # not a valid POST target
    assert res.status_code == 400


@pytest.mark.django_db
def test_a_missing_case_is_404(client):
    import uuid
    claimer = AccountFactory()
    res = client.post(f"/api/v1/cases/{uuid.uuid4()}/status", {"status": "rescued"},
                      content_type="application/json", **_hdr(claimer))
    assert res.status_code == 404
