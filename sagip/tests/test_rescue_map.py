"""US-S4 — the public rescue map: a PostGIS proximity query, city-level output only."""
import pytest
from django.contrib.gis.geos import Point

from sagip.models import StrayReport

# Marikina City centroid (lat, lng) — the reference point for ?city=Marikina.
MARIKINA_LAT, MARIKINA_LNG = 14.6507, 121.1029


def _report(lat, lng, status="reported", species="dog", condition="injured"):
    return StrayReport.objects.create(species=species, condition=condition, status=status,
                                      geom=Point(lng, lat, srid=4326))


@pytest.mark.django_db
def test_map_is_public_no_auth_required(client):
    assert client.get("/api/v1/reports/map?city=Marikina").status_code == 200


@pytest.mark.django_db
def test_map_returns_reports_near_the_chosen_city(client):
    near = _report(14.65, 121.10)  # ~1 km from the Marikina centroid
    ids = [r["report_id"] for r in
           client.get("/api/v1/reports/map?city=Marikina").json()["reports"]]
    assert str(near.report_id) in ids


@pytest.mark.django_db
def test_map_excludes_reports_outside_the_radius(client):
    far = _report(15.30, 121.10)  # ~70 km north
    ids = [r["report_id"] for r in
           client.get("/api/v1/reports/map?city=Marikina&radius_km=10").json()["reports"]]
    assert str(far.report_id) not in ids


@pytest.mark.django_db
def test_map_response_is_city_level_never_the_precise_point(client):
    _report(14.65, 121.10)
    r = client.get("/api/v1/reports/map?city=Marikina").json()["reports"][0]
    assert set(r.keys()) == {"report_id", "species", "condition", "status", "city", "reported_at"}
    assert "lat" not in r and "lng" not in r and "geom" not in r  # §12.5 — no exact spot


@pytest.mark.django_db
def test_map_filters_by_status(client):
    _report(14.65, 121.10, status="reported")
    _report(14.651, 121.101, status="resolved")
    res = client.get("/api/v1/reports/map?city=Marikina&status=reported")
    assert {r["status"] for r in res.json()["reports"]} == {"reported"}


@pytest.mark.django_db
def test_map_orders_nearest_first(client):
    far = _report(14.70, 121.14)     # further, still within a wide radius
    near = _report(14.651, 121.103)  # very close to the centroid
    ids = [r["report_id"] for r in
           client.get("/api/v1/reports/map?city=Marikina&radius_km=30").json()["reports"]]
    assert ids.index(str(near.report_id)) < ids.index(str(far.report_id))


@pytest.mark.django_db
def test_map_unknown_city_returns_empty(client):
    _report(14.65, 121.10)
    assert client.get("/api/v1/reports/map?city=Atlantis").json()["reports"] == []


@pytest.mark.django_db
def test_map_no_reports_returns_the_empty_shape(client):
    assert client.get("/api/v1/reports/map?city=Marikina").json() == {"reports": []}
