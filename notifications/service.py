"""Write side of notifications (US-X1).

`notify()` is the one place a notification row is created, so every feature that tells a
user something goes through the same door. In-app only this sprint; Sprint 5 (E10) adds
push on top of these rows.
"""
from notifications.models import Notification


def notify(account, type, *, title="", body="", data=None):
    """Create an unread in-app notification for `account`. `type` is the free-text
    catalogue key (e.g. 'verification_approved'); `data` is the deep-link payload the
    client routes on."""
    return Notification.objects.create(
        account=account, type=type, title=title, body=body, data=data)
