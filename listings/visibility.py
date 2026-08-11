from django.db.models import Q


def public_poster_q():
    """The public-visibility predicate for a listing's poster (§3.5): a **Verified
    Member** (an approved `rescuer` capability) **OR** a **verified shelter** (an
    approved `shelter_org` verification_request). Written once here because Sprint 3
    reuses it — keep both arms in sync with the derivation rule, never a stored flag."""
    return (
        Q(posted_by__capabilities__capability="rescuer",
          posted_by__capabilities__status="approved")
        | Q(posted_by__verifications__type="shelter_org",
            posted_by__verifications__status="approved")
    )
