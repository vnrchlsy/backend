"""Write side of notifications (US-X1).

`notify()` is the one place a notification row is created, so every feature that tells a
user something goes through the same door. In-app only this sprint; Sprint 5 (E10) adds
push on top of these rows.
"""
from notifications.models import Notification
from notifications.types import is_registered


class UnregisteredNotificationType(Exception):
    """US-N1 · `type` isn't in `notifications.types.REGISTRY`. Raised at the one write
    door rather than left to silently ship a notification no client knows how to route —
    register the type (with its `data` shape) instead of catching this."""


def notify(account, type, *, title="", body="", data=None):
    """Create an unread in-app notification for `account`. `type` must be a key in
    `notifications.types.REGISTRY`; `data` is the deep-link payload the client routes on."""
    if not is_registered(type):
        raise UnregisteredNotificationType(type)
    return Notification.objects.create(
        account=account, type=type, title=title, body=body, data=data)
