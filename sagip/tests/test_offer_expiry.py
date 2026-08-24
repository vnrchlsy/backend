"""US-N2 — the offer-expiry sweep. Nothing wrote `report_offer.status='expired'` before
this existed; US-E2's "a reopened case still has people to re-ask" arithmetic (see
sagip/sweeps.py's expire_stalled_claims) silently assumed it did.
"""
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from accounts.factories import AccountFactory
from sagip.models import OfferStatus, ReportOffer, StrayReport
from sagip.sweeps import expire_offers

NOW = timezone.now()


def _report(**kw):
    defaults = dict(species="dog", condition="healthy", status="reported",
                    geom=Point(121.05, 14.63, srid=4326))
    defaults.update(kw)
    return StrayReport.objects.create(**defaults)


def _offer(status=OfferStatus.OPEN, expires_at=None, **kw):
    defaults = dict(report=_report(), account=AccountFactory(), offer_type="transport",
                    status=status, expires_at=expires_at or NOW - timezone.timedelta(hours=1))
    defaults.update(kw)
    return ReportOffer.objects.create(**defaults)


@pytest.mark.django_db
def test_expires_an_open_offer_past_its_window():
    offer = _offer(status=OfferStatus.OPEN, expires_at=NOW - timezone.timedelta(hours=1))
    count = expire_offers(now=NOW)
    offer.refresh_from_db()
    assert count == 1
    assert offer.status == OfferStatus.EXPIRED


@pytest.mark.django_db
def test_does_not_expire_before_the_window():
    offer = _offer(status=OfferStatus.OPEN, expires_at=NOW + timezone.timedelta(hours=1))
    count = expire_offers(now=NOW)
    offer.refresh_from_db()
    assert count == 0
    assert offer.status == OfferStatus.OPEN


@pytest.mark.django_db
def test_never_touches_a_matched_offer_even_past_its_window():
    offer = _offer(status=OfferStatus.MATCHED, expires_at=NOW - timezone.timedelta(hours=1))
    expire_offers(now=NOW)
    offer.refresh_from_db()
    assert offer.status == OfferStatus.MATCHED


@pytest.mark.django_db
def test_is_idempotent():
    _offer(status=OfferStatus.OPEN, expires_at=NOW - timezone.timedelta(hours=1))
    first = expire_offers(now=NOW)
    second = expire_offers(now=NOW)
    assert first == 1
    assert second == 0


@pytest.mark.django_db
def test_only_touches_offers_past_their_own_window():
    stale = _offer(status=OfferStatus.OPEN, expires_at=NOW - timezone.timedelta(hours=1))
    fresh = _offer(status=OfferStatus.OPEN, expires_at=NOW + timezone.timedelta(hours=1))
    expire_offers(now=NOW)
    stale.refresh_from_db()
    fresh.refresh_from_db()
    assert stale.status == OfferStatus.EXPIRED
    assert fresh.status == OfferStatus.OPEN
