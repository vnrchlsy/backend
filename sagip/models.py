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


class RescueCase(models.Model):
    """US-S6 scaffolding · an exclusive, binding claim on a stray report (kupkop_mvp_schema.sql
    `rescue_case`). Sprint 3 owns the claim flow that writes these; this sprint only stands the
    table up. `report` is UNIQUE among ACTIVE claims (partial unique, expired_at IS NULL), not
    unique forever: a stalled claim can expire (Sprint 3) and the report reverts to `reported` to
    be re-claimed, while the expired row survives as the accountability signal — so exclusivity is
    'one live claim', matching the DDL's `idx_rescue_case_active`, not the pre-expiry plain UNIQUE."""

    case_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(StrayReport, on_delete=models.CASCADE, related_name="cases")
    claimed_by_account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                           related_name="claimed_cases")
    claimed_at = models.DateTimeField(auto_now_add=True)
    outcome_notes = models.TextField(blank=True)
    outcome_photo_url = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Set when a stalled claim auto-expires (Sprint 3); the report reverts to reported and can be
    # re-claimed while this row is kept. NULL = active claim.
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rescue_case"
        constraints = [
            models.UniqueConstraint(fields=["report"],
                                    condition=models.Q(expired_at__isnull=True),
                                    name="idx_rescue_case_active"),
        ]


class CaseStatusHistory(models.Model):
    """US-S6 · an append-only audit of every stray-report status change (kupkop_mvp_schema.sql
    `case_status_history`). Written only via `set_report_status()` so a status can never move
    unlogged — Sprint 3 builds the claim/resolve transitions on top of that single writer."""

    history_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(StrayReport, on_delete=models.CASCADE, related_name="status_history")
    status = models.CharField(max_length=10, choices=StrayStatus.choices)
    # SET_NULL, not CASCADE: an account leaving must not erase the audit trail of what it changed.
    changed_by_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True,
                                           blank=True, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "case_status_history"
        indexes = [models.Index(fields=["report", "-changed_at"], name="idx_case_history_report")]
