import datetime

import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from notifications.models import Notification


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


@pytest.mark.django_db
def test_notifications_require_auth(client):
    assert client.get("/api/v1/me/notifications").status_code == 401


@pytest.mark.django_db
def test_lists_the_users_notifications_newest_first(client):
    acc = AccountFactory()
    old = Notification.objects.create(account=acc, type="verification_needs_info", title="old")
    new = Notification.objects.create(account=acc, type="verification_approved", title="new")
    now = timezone.now()
    Notification.objects.filter(pk=old.pk).update(created_at=now - datetime.timedelta(hours=2))
    Notification.objects.filter(pk=new.pk).update(created_at=now)
    res = client.get("/api/v1/me/notifications", **_hdr(acc))
    assert res.status_code == 200
    types = [n["type"] for n in res.json()["notifications"]]
    assert types == ["verification_approved", "verification_needs_info"]


@pytest.mark.django_db
def test_only_returns_the_callers_own_notifications(client):
    me, other = AccountFactory(), AccountFactory()
    Notification.objects.create(account=other, type="verification_approved")
    res = client.get("/api/v1/me/notifications", **_hdr(me))
    assert res.json()["notifications"] == []


@pytest.mark.django_db
def test_mark_read_marks_the_users_unread_notifications(client):
    acc = AccountFactory()
    Notification.objects.create(account=acc, type="verification_approved", read=False)
    res = client.post("/api/v1/me/notifications/read", **_hdr(acc))
    assert res.status_code == 200
    assert not Notification.objects.filter(account=acc, read=False).exists()


@pytest.mark.django_db
def test_mark_read_does_not_touch_another_users_notifications(client):
    me, other = AccountFactory(), AccountFactory()
    n = Notification.objects.create(account=other, type="verification_approved", read=False)
    client.post("/api/v1/me/notifications/read", **_hdr(me))
    n.refresh_from_db()
    assert n.read is False
