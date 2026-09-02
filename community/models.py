import uuid

from django.db import models

from accounts.models import Account


class NeedCategory(models.TextChoices):
    FOOD = "food"
    MEDICINE = "medicine"
    SUPPLIES = "supplies"
    FUNDS = "funds"
    OTHER = "other"


class NeedStatus(models.TextChoices):
    OPEN = "open"
    FULFILLED = "fulfilled"
    CLOSED = "closed"


class PledgeStatus(models.TextChoices):
    PLEDGED = "pledged"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ShelterNeed(models.Model):
    """A shelter's Abot-tulong wishlist item (kupkop_mvp_schema.sql `shelter_need`).

    `quantity_received` is a running total the shelter grows via received-confirm — never a
    pledge, which is only a promise (D-S6-7). The `open -> fulfilled` flip and all
    `quantity_received` arithmetic live in ONE writer (`community/needs.py::apply_received`),
    under a row lock, so two staff confirming at once can't double-count. `fulfilled`/`closed`
    take no new pledges.

    No `updated_at`: the DDL doesn't carry one for this table, and status/received changes are
    already auditable through the pledge rows that drove them.
    """

    need_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shelter_account = models.ForeignKey(Account, on_delete=models.CASCADE,
                                        related_name="shelter_needs")
    title = models.CharField(max_length=120)
    category = models.CharField(max_length=10, choices=NeedCategory.choices)
    description = models.TextField(blank=True)
    quantity_needed = models.IntegerField(default=1)
    quantity_received = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=NeedStatus.choices,
                              default=NeedStatus.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shelter_need"
        indexes = [
            models.Index(fields=["shelter_account", "status"], name="idx_shelter_need_shelter"),
            models.Index(fields=["category"], name="idx_shelter_need_category"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity_needed__gte=1),
                                   name="shelter_need_needed_min1"),
            models.CheckConstraint(condition=models.Q(quantity_received__gte=0),
                                   name="shelter_need_received_min0"),
        ]


class NeedPledge(models.Model):
    """One giver's promise against a need (`need_pledge`).

    A pledge is a promise, not inventory: it never touches `shelter_need.quantity_received`
    (only the shelter's received-confirm does, D-S6-7). A `pledged` pledge can be cancelled by
    its pledger; a `delivered` one is a recorded fact and immutable (the attendance posture).
    """

    pledge_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    need = models.ForeignKey(ShelterNeed, on_delete=models.CASCADE, related_name="pledges")
    pledger_account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                        related_name="need_pledges")
    quantity = models.IntegerField(default=1)
    status = models.CharField(max_length=10, choices=PledgeStatus.choices,
                              default=PledgeStatus.PLEDGED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "need_pledge"
        indexes = [
            models.Index(fields=["need"], name="idx_need_pledge_need"),
            models.Index(fields=["pledger_account"], name="idx_need_pledge_pledger"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1),
                                   name="need_pledge_quantity_min1"),
        ]
