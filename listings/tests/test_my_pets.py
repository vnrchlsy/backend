import pytest
from rest_framework.test import APIClient

from accounts.factories import AccountFactory
from listings.models import Pet


@pytest.mark.django_db
def test_me_pets_returns_only_own():
    a = AccountFactory()
    b = AccountFactory()
    Pet.objects.create(owner_account=a, name="Rex", species="dog")
    Pet.objects.create(owner_account=b, name="Bo", species="cat")
    c = APIClient()
    c.force_authenticate(user=a)
    body = c.get("/api/v1/me/pets").json()
    assert [p["name"] for p in body["results"]] == ["Rex"]


@pytest.mark.django_db
def test_me_pets_guest_401():
    assert APIClient().get("/api/v1/me/pets").status_code == 401
