import uuid

from django.db import models

from accounts.models import Account


class OtpChannel(models.TextChoices):
    EMAIL = "email"
    SMS = "sms"


class OtpPurpose(models.TextChoices):
    SIGNUP = "signup"
    PHONE = "phone"
    RESET = "reset"


class VerificationCode(models.Model):
    code_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="codes")
    channel = models.CharField(max_length=10, choices=OtpChannel.choices)
    purpose = models.CharField(max_length=10, choices=OtpPurpose.choices)
    code_hash = models.TextField()
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=5)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "verification_code"
        indexes = [models.Index(fields=["account", "purpose", "-created_at"])]


class VerificationType(models.TextChoices):
    SHELTER_ORG = "shelter_org"
    RESCUER = "rescuer"
    PROVIDER = "provider"


class VerificationStatus(models.TextChoices):
    PENDING = "pending"
    NEEDS_INFO = "needs_info"
    APPROVED = "approved"
    REJECTED = "rejected"


class CapabilityStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VerificationRequest(models.Model):
    verification_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="verifications")
    type = models.CharField(max_length=20, choices=VerificationType.choices)
    status = models.CharField(max_length=20, choices=VerificationStatus.choices, default="pending")
    social_proof_url = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "verification_request"


class VerificationDocument(models.Model):
    document_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.ForeignKey(VerificationRequest, on_delete=models.CASCADE,
                                     related_name="documents")
    doc_type = models.CharField(max_length=30)
    file_url = models.TextField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default="pending")
    review_note = models.TextField(blank=True)

    class Meta:
        db_table = "verification_document"


class CapabilityType(models.TextChoices):
    RESCUER = "rescuer"
    PROVIDER = "provider"


class AccountCapability(models.Model):
    capability_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="capabilities")
    capability = models.CharField(max_length=20, choices=CapabilityType.choices)
    status = models.CharField(max_length=20, choices=CapabilityStatus.choices, default="pending")
    granted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "account_capability"
        constraints = [models.UniqueConstraint(fields=["account", "capability"],
                                               name="uq_account_capability")]
