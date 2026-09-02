import pytest
from django.contrib.gis.geos import Point

from accounts.factories import AccountFactory
from sagip.models import StrayReport, StrayReportPhoto


@pytest.mark.django_db
def test_stray_report_stores_a_geographic_point():
    acc = AccountFactory()
    r = StrayReport.objects.create(
        reporter_account=acc, species="dog", condition="injured",
        geom=Point(121.05, 14.63, srid=4326))
    r.refresh_from_db()
    assert r.status == "reported"          # default
    assert r.escalation_level == 0         # default
    assert r.report_type == "stray"        # default
    assert round(r.geom.x, 2) == 121.05 and round(r.geom.y, 2) == 14.63


@pytest.mark.django_db
def test_photos_cascade_from_a_report():
    r = StrayReport.objects.create(species="cat", condition="healthy",
                                   geom=Point(121.0, 14.6, srid=4326))
    StrayReportPhoto.objects.create(report=r, url="https://example.invalid/p1")
    assert r.photos.count() == 1
