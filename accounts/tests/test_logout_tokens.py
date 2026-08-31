import pytest
from rest_framework.test import APIClient

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from devices.models import DeviceToken


def _auth(a):
    c = APIClient(); c.force_authenticate(user=a); return c


@pytest.mark.django_db
def test_logout_deletes_named_device_token_and_still_204s():
    a = AccountFactory()
    DeviceToken.objects.create(account=a, fcm_token="dev-A", platform="ios")
    DeviceToken.objects.create(account=a, fcm_token="dev-B", platform="ios")
    r = _auth(a).post("/api/v1/auth/logout", {"refresh": tokens_for(a)["refresh"], "fcm_token": "dev-A"}, format="json")
    assert r.status_code == 204
    assert not DeviceToken.objects.filter(fcm_token="dev-A").exists()   # this device's token gone
    assert DeviceToken.objects.filter(fcm_token="dev-B").exists()       # the other stays


@pytest.mark.django_db
def test_logout_without_fcm_token_still_204s():
    a = AccountFactory()
    r = _auth(a).post("/api/v1/auth/logout", {"refresh": tokens_for(a)["refresh"]}, format="json")
    assert r.status_code == 204


@pytest.mark.django_db
def test_logout_all_clears_every_device_token_for_the_account():
    a = AccountFactory(); other = AccountFactory()
    DeviceToken.objects.create(account=a, fcm_token="a1", platform="ios")
    DeviceToken.objects.create(account=a, fcm_token="a2", platform="android")
    DeviceToken.objects.create(account=other, fcm_token="o1", platform="ios")
    assert _auth(a).post("/api/v1/auth/logout-all").status_code == 204
    assert not DeviceToken.objects.filter(account=a).exists()   # all a's tokens gone
    assert DeviceToken.objects.filter(account=other).exists()   # other's untouched
