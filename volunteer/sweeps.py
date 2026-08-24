"""US-V7 · the volunteer reminder sweep.

Windows are Tech Spec §14's: 24 h and 1 h before the shift. (`dev/volunteer-feature.md`
says only "ahead of the shift" — §14's numbers win; reconcile that doc.)

⚠️ Idempotency is DERIVED, not stored. Cron runs this hourly, so without a guard every
approved volunteer would be reminded every hour. Escalation solved the analogous problem
with a stored `escalation_level`; here the notification rows themselves are the record —
a reminder is due only if no `shift_reminder` row exists for that signup AND window. No
migration, and it handles both windows independently (one boolean could not).
"""
from django.utils import timezone

from notifications.models import Notification
from notifications.service import notify

from .models import SignupStatus, VolunteerSignup

# (window label, hours before the shift the window opens)
REMINDER_WINDOWS = [("24h", 24), ("1h", 1)]


def remind_shifts(now=None):
    """Send any due shift reminders. Idempotent. Returns the signups reminded."""
    now = now or timezone.now()
    reminded = []
    for label, hours in REMINDER_WINDOWS:
        opens_at = now + timezone.timedelta(hours=hours)
        due = (VolunteerSignup.objects
               .filter(status=SignupStatus.APPROVED,
                       shift__starts_at__gt=now,
                       shift__starts_at__lte=opens_at)
               .select_related("shift", "volunteer_account"))
        for signup in due:
            already = Notification.objects.filter(
                account=signup.volunteer_account, type="shift_reminder",
                data__signup_id=str(signup.pk), data__window=label).exists()
            if already:
                continue
            notify(signup.volunteer_account, "shift_reminder",
                   title="Your shift is coming up",
                   body=f"Your shift starts {label.replace('h', ' hour')}s from now.",
                   data={"shift_id": str(signup.shift_id), "signup_id": str(signup.pk),
                         "window": label})
            reminded.append(signup)
    return reminded
