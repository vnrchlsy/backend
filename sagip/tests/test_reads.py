"""US-S3 (GET /me/reports) and US-S5 (GET /reports/{id})."""
import uuid

import pytest
from django.contrib.gis.geos import Point

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from sagip.models import StrayReport, StrayReportPhoto


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _report(reporter=None, **kw):
    kw.setdefault("species", "dog")
    kw.setdefault("condition", "injured")
    return StrayReport.objects.create(reporter_account=reporter,
                                      geom=Point(121.05, 14.63, srid=4326), **kw)


# ── US-S3 · my reports ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_my_reports_requires_auth(client):
    assert client.get("/api/v1/me/reports").status_code == 401


@pytest.mark.django_db
def test_my_reports_lists_only_the_callers_reports_with_status(client):
    me, other = AccountFactory(), AccountFactory()
    mine = _report(me, city="Marikina", status="reported")
    _report(other)
    body = client.get("/api/v1/me/reports", **_hdr(me)).json()["results"]
    assert [r["report_id"] for r in body] == [str(mine.report_id)]
    assert set(body[0].keys()) == {"report_id", "species", "condition", "status", "city", "created_at"}
    assert body[0]["status"] == "reported"


# ── US-S5 · report detail (public, shared-link) ───────────────────────────────────
@pytest.mark.django_db
def test_report_detail_is_public_and_city_level(client):
    r = _report(species="cat", condition="sick", notes="Limping badly.",
                city="Pasig", status="reported")
    StrayReportPhoto.objects.create(report=r, url="https://example.invalid/1")
    body = client.get(f"/api/v1/reports/{r.report_id}").json()
    assert body["report_id"] == str(r.report_id)
    assert body["species"] == "cat" and body["condition"] == "sick"
    assert body["notes"] == "Limping badly." and body["status"] == "reported"
    assert body["city"] == "Pasig"
    assert body["photos"] == ["https://example.invalid/1"]
    # §12.5 — a shared link never exposes the exact spot
    assert "lat" not in body and "lng" not in body and "geom" not in body


@pytest.mark.django_db
def test_report_detail_404_for_unknown_id(client):
    assert client.get(f"/api/v1/reports/{uuid.uuid4()}").status_code == 404
