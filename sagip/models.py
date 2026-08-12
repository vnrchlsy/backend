import uuid

from django.contrib.gis.db import models  # GeoDjango: PointField + spatial manager

from accounts.models import Account


class ReportType(models.TextChoices):
    STRAY = "stray"
    LOST = "lost"
    FOUND = "found"


class Species(models.TextChoices):
    DOG = "dog"
    CAT = "cat"
    OTHER = "other"


class StrayCondition(models.TextChoices):
    INJURED = "injured"
    SICK = "sick"
    HEALTHY = "healthy"
    PREGNANT = "pregnant"


class StrayStatus(models.TextChoices):
    # Only 'reported' is amber (someone still needs to act). Sprint 3 owns the transitions.
    REPORTED = "reported"
    CLAIMED = "claimed"
    RESCUED = "rescued"
    SAFE = "safe"
    RESOLVED = "resolved"


class StrayReport(models.Model):
    """A stray sighting (matches kupkop_mvp_schema.sql `stray_report`). `geom` is the one
    precise-GPS surface in the app (decision 11) — a PostGIS point; everywhere else a
    person's location is a city. `reporter_account_id` is always stored even when
    `is_anonymous` (which only hides the reporter from *other users*, not from the row)."""

    report_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report_type = models.CharField(max_length=10, choices=ReportType.choices,
                                   default=ReportType.STRAY)
    reporter_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True,
                                         blank=True, related_name="stray_reports")
    # pet_id exists in the DDL (lost & found links a report to a pet), but there is no Pet
    # Django model yet — kept as a nullable id column so the schema stays faithful.
    pet_id = models.UUIDField(null=True, blank=True)
    is_anonymous = models.BooleanField(default=False)
    species = models.CharField(max_length=10, choices=Species.choices)
    condition = models.CharField(max_length=10, choices=StrayCondition.choices)
    notes = models.TextField(blank=True)
    geom = models.PointField(geography=True, srid=4326)   # NOT NULL — a report needs a place
    location_text = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=10, choices=StrayStatus.choices,
                              default=StrayStatus.REPORTED)
    escalation_level = models.SmallIntegerField(default=0)  # 0 as-reported · 1 ~5km · 2 partners
    # Derived from geom (reverse-geocode) at write; NULL if unresolved — out of MVP scope.
    city = models.CharField(max_length=80, null=True, blank=True)
    barangay = models.CharField(max_length=80, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stray_report"


class StrayReportPhoto(models.Model):
    photo_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(StrayReport, on_delete=models.CASCADE, related_name="photos")
    url = models.TextField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stray_report_photo"
