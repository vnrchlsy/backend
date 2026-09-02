"""US-V1b · the single writer for a volunteer signup's status.

Every transition goes through here so the timestamp rules live in one place. Mirrors
`sagip/status.py::set_report_status` and `listings/stages.py::set_stage_state`.

⚠️ No history table, deliberately. Sibling modules keep append-only logs
(`CaseStatusHistory`, `AdoptionStageHistory`) because a rescue case cycles and an adoption
funnel has six stages — information is genuinely lost without one. A signup moves through at
most two states and ends terminal, and the reliability counts read final statuses, so nothing
is lost. Revisit if signups ever gain a reopen path.
"""
from django.db import transaction
from django.utils import timezone

from .models import SignupStatus


class StatusError(ValueError):
    """A status move that can't be applied — e.g. an unknown target status."""


@transaction.atomic
def set_signup_status(signup, status, *, now=None):
    """Move `signup` to `status`, stamping `cancelled_at` when it becomes cancelled.

    `cancelled_at` is written here and only here. It is a dedicated column rather than a read
    of `updated_at` because the 12h free-vs-late audit must survive later writes, which
    overwrite `updated_at` (DDL caveat L4 / the `adoption_inquiry.decided_at` precedent).
    Returns the saved signup.
    """
    if status not in SignupStatus.values:
        raise StatusError(f"unknown signup status: {status!r}")

    fields = ["status", "updated_at"]
    signup.status = status
    if status == SignupStatus.CANCELLED and signup.cancelled_at is None:
        signup.cancelled_at = now or timezone.now()
        fields.append("cancelled_at")
    signup.save(update_fields=fields)
    return signup
