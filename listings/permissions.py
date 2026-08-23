from rest_framework.permissions import IsAuthenticated

from listings.visibility import account_is_verified_rescuer


class IsVerifiedRescuer(IsAuthenticated):
    """An approved rescuer capability (Verified Member) or an approved shelter_org
    verification (verified shelter) — the same predicate that gates public listing
    visibility (`public_poster_q`). Originally written for Sprint 3's claim gate
    (US-K1); centralised here (rather than duplicated in sagip) since this is the app
    that owns `account_is_verified_rescuer`. Sprint 4's listing/inquiry endpoints
    (US-A2/US-A4) reuse it directly — an unverified caller gets 403, which the app
    renders as the get-verified gate."""

    message = "This action requires a Verified Member badge or a verified shelter account."

    def has_permission(self, request, view):
        return (super().has_permission(request, view)
                and account_is_verified_rescuer(request.user))


class IsVerifiedMember(IsAuthenticated):
    """US-A4 · only an approved `rescuer` capability (Verified Member) may inquire —
    deliberately narrower than `IsVerifiedRescuer`. Adopting is the Pet-Owner path
    (decision 3); a verified SHELTER receiving an inquiry on someone else's listing
    isn't the scenario this gates, so it doesn't get the OR-with-shelter treatment
    listing/claim visibility does."""

    message = "This action requires a Verified Member badge."
    # US-A4's contract names this exact code (`403 {code:"member_badge_required"}`) — DRF
    # reads `permission.code` and threads it into the error body via
    # common.errors.error_handler, so this is the one line that makes the two agree.
    code = "member_badge_required"

    def has_permission(self, request, view):
        return (super().has_permission(request, view)
                and request.user.capabilities.filter(capability="rescuer",
                                                      status="approved").exists())
