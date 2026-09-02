from rest_framework.permissions import IsAuthenticated

from listings.visibility import account_is_verified_rescuer


class IsVerifiedRescuer(IsAuthenticated):
    """US-K1 · only an approved rescuer capability (Verified Member) or an approved
    shelter_org verification (verified shelter) may claim a case — the exact predicate
    that already gates public listing visibility (listings/visibility.py::
    public_poster_q). An unverified caller gets 403, which the app renders as the
    get-verified gate (`rescue-claim-gate`)."""

    message = "Claiming a case requires a Verified Member badge or a verified shelter account."

    def has_permission(self, request, view):
        return (super().has_permission(request, view)
                and account_is_verified_rescuer(request.user))
