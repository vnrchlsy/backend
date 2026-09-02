import pytest

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for


@pytest.mark.django_db
def test_admin_index_reachable_by_staff(admin_client):
    res = admin_client.get("/admin/")
    assert res.status_code == 200


@pytest.mark.django_db
def test_anonymous_redirected_from_admin(client):
    res = client.get("/admin/")
    assert res.status_code == 302
    assert "/admin/login/" in res.headers["Location"]


@pytest.mark.django_db
def test_non_staff_django_user_cannot_reach_admin(client, django_user_model):
    user = django_user_model.objects.create_user("bob", password="irrelevant")  # is_staff=False
    client.force_login(user)
    res = client.get("/admin/")
    assert res.status_code == 302
    assert "/admin/login/" in res.headers["Location"]


@pytest.mark.django_db
def test_jwt_bearer_does_not_grant_admin_access(client):
    # A shelter/owner account authenticates the API with a JWT, never a Django session.
    # The admin gate must ignore the Bearer token entirely — this is the "a shelter or
    # owner account cannot reach it" criterion (US-R1).
    acc = AccountFactory(account_type="shelter")
    res = client.get("/admin/", HTTP_AUTHORIZATION=f"Bearer {tokens_for(acc)['access']}")
    assert res.status_code == 302
    assert "/admin/login/" in res.headers["Location"]
