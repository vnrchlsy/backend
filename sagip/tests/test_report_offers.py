"""US-O1 (offer help) + US-O2 (withdraw / see my offers).

An offer is a non-exclusive commitment (decision 12) — it never touches
`stray_report.status`, unlike a claim. These tests check that boundary explicitly, since
it's the exact silent-failure shape decision 12 calls out (a supported-but-unclaimed
report must stay amber).
"""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from notifications.models import Notification
from sagip.models import OfferStatus, OfferType, ReportOffer, StrayReport


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _report(**kw):
    defaults = dict(species="dog", condition="injured", city="Marikina", status="reported",
                    geom=Point(121.05, 14.63, srid=4326))
    defaults.update(kw)
    return StrayReport.objects.create(**defaults)


def _offer_post(client, report, acc, offer_type="transport"):
    return client.post(f"/api/v1/reports/{report.pk}/offers", {"offer_type": offer_type},
                       content_type="application/json", **_hdr(acc))


# ── US-O1 · offer help ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_guest_cannot_offer(client):
    report = _report()
    res = client.post(f"/api/v1/reports/{report.pk}/offers", {"offer_type": "transport"},
                      content_type="application/json")
    assert res.status_code == 401


@pytest.mark.django_db
def test_any_signed_in_user_can_offer_no_verification_needed(client):
    report = _report()
    res = _offer_post(client, report, AccountFactory())
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "open" and body["offer_id"] and body["expires_at"]


@pytest.mark.django_db
def test_the_offer_window_is_48_hours(client):
    report = _report()
    res = _offer_post(client, report, AccountFactory())
    offer = ReportOffer.objects.get(pk=res.json()["offer_id"])
    delta = offer.expires_at - offer.created_at
    assert 47.9 < delta.total_seconds() / 3600 < 48.1


@pytest.mark.django_db
def test_offering_never_moves_the_report_status(client):
    report = _report()
    _offer_post(client, report, AccountFactory())
    report.refresh_from_db()
    assert report.status == "reported"  # decision 12 — offers never move stray_status


@pytest.mark.django_db
def test_offering_on_a_claimed_report_is_409(client):
    report = _report(status="claimed")
    res = _offer_post(client, report, AccountFactory())
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "report_not_open"


@pytest.mark.django_db
def test_offering_on_a_resolved_report_is_409(client):
    report = _report(status="resolved")
    res = _offer_post(client, report, AccountFactory())
    assert res.status_code == 409


@pytest.mark.django_db
def test_the_same_type_twice_from_the_same_account_is_rejected(client):
    report = _report()
    offerer = AccountFactory()
    ok = _offer_post(client, report, offerer, "transport")
    assert ok.status_code == 201
    dup = _offer_post(client, report, offerer, "transport")
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "already_offered"
    assert ReportOffer.objects.filter(report=report, account=offerer,
                                      offer_type="transport").count() == 1


@pytest.mark.django_db
def test_one_person_can_offer_two_different_types(client):
    report = _report()
    offerer = AccountFactory()
    assert _offer_post(client, report, offerer, "transport").status_code == 201
    assert _offer_post(client, report, offerer, "supplies").status_code == 201
    assert ReportOffer.objects.filter(report=report, account=offerer).count() == 2


@pytest.mark.django_db
def test_offering_notifies_the_reporter(client):
    reporter = AccountFactory()
    report = _report(reporter_account=reporter)
    _offer_post(client, report, AccountFactory())
    assert Notification.objects.filter(account=reporter, type="offer_received").exists()


@pytest.mark.django_db
def test_offering_on_a_report_with_no_reporter_account_does_not_error(client):
    report = _report(reporter_account=None)
    res = _offer_post(client, report, AccountFactory())
    assert res.status_code == 201


@pytest.mark.django_db
def test_offering_on_a_missing_report_is_404(client):
    res = client.post(f"/api/v1/reports/{uuid.uuid4()}/offers", {"offer_type": "transport"},
                      content_type="application/json", **_hdr(AccountFactory()))
    assert res.status_code == 404


# ── US-O2 · withdraw / my offers ───────────────────────────────────────────────────
@pytest.mark.django_db
def test_withdrawing_an_open_offer_deletes_it(client):
    report = _report()
    offerer = AccountFactory()
    offer_id = _offer_post(client, report, offerer).json()["offer_id"]
    res = client.delete(f"/api/v1/reports/{report.pk}/offers/{offer_id}", **_hdr(offerer))
    assert res.status_code == 204
    assert not ReportOffer.objects.filter(pk=offer_id).exists()


@pytest.mark.django_db
def test_only_the_offerer_can_withdraw(client):
    report = _report()
    offerer, someone_else = AccountFactory(), AccountFactory()
    offer_id = _offer_post(client, report, offerer).json()["offer_id"]
    res = client.delete(f"/api/v1/reports/{report.pk}/offers/{offer_id}", **_hdr(someone_else))
    assert res.status_code == 403
    assert ReportOffer.objects.filter(pk=offer_id).exists()


@pytest.mark.django_db
def test_a_matched_offer_cannot_be_withdrawn(client):
    report = _report()
    offerer = AccountFactory()
    offer = ReportOffer.objects.create(report=report, account=offerer,
                                       offer_type=OfferType.TRANSPORT,
                                       status=OfferStatus.MATCHED,
                                       expires_at=timezone.now() + timezone.timedelta(hours=48))
    res = client.delete(f"/api/v1/reports/{report.pk}/offers/{offer.pk}", **_hdr(offerer))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_withdrawable"
    assert ReportOffer.objects.filter(pk=offer.pk).exists()


@pytest.mark.django_db
def test_withdrawing_a_missing_offer_is_404(client):
    report = _report()
    res = client.delete(f"/api/v1/reports/{report.pk}/offers/{uuid.uuid4()}",
                        **_hdr(AccountFactory()))
    assert res.status_code == 404


@pytest.mark.django_db
def test_my_offers_lists_only_my_own_newest_first(client):
    me, other = AccountFactory(), AccountFactory()
    r1, r2 = _report(species="dog"), _report(species="cat")
    older = ReportOffer.objects.create(report=r1, account=me, offer_type="transport",
                                       status="open",
                                       expires_at=timezone.now() + timezone.timedelta(hours=48))
    ReportOffer.objects.filter(pk=older.pk).update(
        created_at=timezone.now() - timezone.timedelta(hours=1))
    newer = ReportOffer.objects.create(report=r2, account=me, offer_type="vet_costs",
                                       status="matched",
                                       expires_at=timezone.now() + timezone.timedelta(hours=48))
    ReportOffer.objects.create(report=r1, account=other, offer_type="transport", status="open",
                               expires_at=timezone.now() + timezone.timedelta(hours=48))

    res = client.get("/api/v1/me/offers", **_hdr(me))
    body = res.json()["offers"]
    assert [o["offer_id"] for o in body] == [str(newer.pk), str(older.pk)]
    assert body[0]["status"] == "matched" and body[0]["report"]["species"] == "cat"
    # report_id lets the client link an offer row back to the report it's on
    assert body[0]["report"]["report_id"] == str(r2.pk)
