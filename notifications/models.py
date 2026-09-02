import uuid

from django.db import models

from accounts.models import Account


class Notification(models.Model):
    """An in-app notification row (matches kupkop_mvp_schema.sql `notification`). The bell
    surface reads these; push delivery (device tokens, the §14 matrix) is Sprint 5 (E10) —
    writing the row now means Sprint 5 turns push on rather than retrofitting the triggers.
    `type` is free-text so a new kind needs no migration; `data` carries the deep-link
    payload the client routes on."""

    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=60)
    title = models.CharField(max_length=140, blank=True)
    body = models.TextField(blank=True)
    data = models.JSONField(null=True, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification"
        indexes = [models.Index(fields=["account", "read", "-created_at"],
                                name="idx_notification_account")]
