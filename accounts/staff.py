"""Option A staff bridge helpers (US-R1).

A Kupkop reviewer authenticates the admin as a Django `contrib.auth.User`; the decision
they record must be attributed to an `Account(account_type='admin')`. `reviewer_account`
resolves the one to the other via `StaffProfile`.
"""
from accounts.models import StaffProfile


def reviewer_account(user):
    """Return the admin Account a staff Django `User` acts as, or None if unlinked.

    None means the staffer has no `StaffProfile` — a setup error the caller must surface,
    never silently stamp an anonymous review.
    """
    sp = StaffProfile.objects.filter(user=user).select_related("account").first()
    return sp.account if sp else None
