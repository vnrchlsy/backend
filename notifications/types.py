"""US-N1 · the notification-type registry.

Before this existed, `type` was free-text at every `notify()` call site with no shared
source of truth — and building `NotificationsScreen` in Sprint 3 required hand-maintaining
a *second*, mobile-side list (`mobile_app/src/notifications.ts::notificationTarget()`),
kept in sync with these call sites by hand because there was nothing to import. This is
the backend half of closing that gap: every type any `notify()` call site actually uses,
recorded once, with the `data` shape a client needs to deep-link a tap. `notify()` (see
`notifications/service.py`) refuses an unregistered type outright, so a typo'd or
newly-invented type can't silently ship a notification nothing knows how to route.

This is also the input Sprint 5's push matrix (§14) consumes — build the registry before
the delivery channel multiplies types further.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationType:
    key: str
    # Documents what `data` carries, for readers (this repo's and the mobile client's) —
    # not runtime-validated against the dict a call site actually passes; each call site
    # already builds `data` at the point that has the real values.
    data_shape: str


_TYPES = [
    NotificationType("verification_approved", "{verification_id, type}"),
    NotificationType("verification_rejected", "{verification_id, type}"),
    NotificationType("verification_needs_info", "{verification_id, type}"),
    NotificationType("report_escalated", "{report_id, escalation_level}"),
    NotificationType("case_reopened", "{report_id}"),
    NotificationType("offer_matched", "{report_id, case_id}"),
    NotificationType("report_claimed", "{report_id, case_id}"),
    NotificationType("offer_received", "{report_id, offer_id}"),
    NotificationType("inquiry_received", "{listing_id, inquiry_id}"),
    NotificationType("stage_advanced", "{inquiry_id, stage_key}"),
    NotificationType("signup_requested", "{shift_id, signup_id}"),
    NotificationType("shift_confirmed", "{shift_id, signup_id}"),
    NotificationType("signup_declined", "{shift_id, signup_id}"),
    NotificationType("shift_cancelled_by_shelter", "{shift_id}"),
    NotificationType("shift_reminder", "{shift_id, signup_id, window}"),
]

REGISTRY = {t.key: t for t in _TYPES}


def is_registered(type_key):
    return type_key in REGISTRY
