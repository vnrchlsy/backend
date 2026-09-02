from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Enable PostGIS before any spatial column is created. Runs on dev, CI and staging
    (US-S1 groundwork) — `CREATE EXTENSION IF NOT EXISTS postgis`, idempotent."""

    initial = True
    dependencies = []
    operations = [CreateExtension("postgis")]
