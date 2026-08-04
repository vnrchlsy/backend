import uuid

from django.db import models

from accounts.models import Account


class AdoptionListing(models.Model):
    listing_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    posted_by = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="listings")
    name = models.CharField(max_length=80)
    species = models.CharField(max_length=20)
    breed = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80)
    listing_status = models.CharField(max_length=20, default="available")

    class Meta:
        db_table = "adoption_listing"
