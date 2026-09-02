import pytest

from accounts.factories import AccountFactory
from notifications.models import Notification
from notifications.service import notify


@pytest.mark.django_db
def test_notify_creates_an_unread_row_for_the_account():
    acc = AccountFactory()
    n = notify(acc, "verification_approved", title="You're verified",
               body="Your shelter verification was approved.",
               data={"verification_id": "abc"})
    assert Notification.objects.filter(account=acc).count() == 1
    n.refresh_from_db()
    assert n.type == "verification_approved"
    assert n.read is False
    assert n.data == {"verification_id": "abc"}
    assert n.title == "You're verified"
