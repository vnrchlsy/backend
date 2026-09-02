"""US-S6 · rescue_case + case_status_history scaffolding and the set_report_status writer."""
import pytest
from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.factories import AccountFactory
from sagip.models import CaseStatusHistory, RescueCase, StrayReport, StrayStatus
from sagip.status import StatusError, set_report_status


def _report():
    return StrayReport.objects.create(species="dog", condition="injured",
                                      geom=Point(121.05, 14.63, srid=4326))


@pytest.mark.django_db
def test_set_report_status_moves_status_and_logs_it():
    r = _report()
    actor = AccountFactory()
    row = set_report_status(r, StrayStatus.CLAIMED, actor, note="Picked up by a rescuer")
    r.refresh_from_db()

    assert r.status == StrayStatus.CLAIMED
    assert CaseStatusHistory.objects.filter(report=r).count() == 1
    assert row.status == StrayStatus.CLAIMED
    assert row.changed_by_account_id == actor.pk
    assert row.note == "Picked up by a rescuer"


@pytest.mark.django_db
def test_every_move_appends_a_history_row_in_order():
    r = _report()
    actor = AccountFactory()
    for s in (StrayStatus.CLAIMED, StrayStatus.RESCUED, StrayStatus.SAFE):
        set_report_status(r, s, actor)
    logged = list(CaseStatusHistory.objects.filter(report=r).order_by("changed_at")
                  .values_list("status", flat=True))
    assert logged == [StrayStatus.CLAIMED, StrayStatus.RESCUED, StrayStatus.SAFE]
    r.refresh_from_db()
    assert r.status == StrayStatus.SAFE


@pytest.mark.django_db
def test_unknown_status_is_rejected_and_leaves_the_report_untouched():
    r = _report()
    with pytest.raises(StatusError):
        set_report_status(r, "teleported", AccountFactory())
    r.refresh_from_db()
    assert r.status == StrayStatus.REPORTED
    assert CaseStatusHistory.objects.filter(report=r).count() == 0


@pytest.mark.django_db
def test_history_survives_the_actor_being_deleted():
    r = _report()
    actor = AccountFactory()
    set_report_status(r, StrayStatus.CLAIMED, actor)
    actor.delete()
    row = CaseStatusHistory.objects.get(report=r)
    assert row.changed_by_account_id is None   # SET_NULL — the audit row is kept


@pytest.mark.django_db
def test_only_one_active_claim_per_report():
    r = _report()
    a, b = AccountFactory(), AccountFactory()
    RescueCase.objects.create(report=r, claimed_by_account=a)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RescueCase.objects.create(report=r, claimed_by_account=b)


@pytest.mark.django_db
def test_an_expired_claim_frees_the_report_to_be_reclaimed():
    r = _report()
    a, b = AccountFactory(), AccountFactory()
    RescueCase.objects.create(report=r, claimed_by_account=a, expired_at=timezone.now())
    # The first claim expired, so a fresh active claim on the same report is allowed.
    fresh = RescueCase.objects.create(report=r, claimed_by_account=b)
    assert fresh.expired_at is None
    assert r.cases.count() == 2
