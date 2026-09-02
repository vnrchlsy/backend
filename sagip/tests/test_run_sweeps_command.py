"""US-F0 — the `run_sweeps` management command wires both sweeps together and is
runnable from cron/dev without a scheduler in the loop."""
import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.utils import timezone

from sagip.models import StrayReport


@pytest.mark.django_db
def test_run_sweeps_reports_what_it_did(capsys):
    StrayReport.objects.create(
        species="dog", condition="injured", status="reported",
        geom=Point(121.05, 14.63, srid=4326))
    StrayReport.objects.filter().update(
        created_at=timezone.now() - timezone.timedelta(hours=5))

    call_command("run_sweeps")
    out = capsys.readouterr().out
    assert "escalated" in out and "expired" in out
