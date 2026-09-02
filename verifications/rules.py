"""The tier -> required-document rule (§3.5) — the single source both the submit path
and the reviewer surface derive from.

Sprint 1 encoded this once inside `verifications/views.py::_shelter_doc_error` (the
submit check). US-R4 needs the *same* rule on the reviewer's side to show "what's
missing" before a decision. Two copies would drift, and the failure mode is a
wrongly-granted Verified Shelter badge — so the knowledge lives here and both import it.
"""
# Tier-1 base (community rescue submits exactly this; a registered NGO must include it
# too, plus the NGO papers). `rescue_photos` needs at least MIN_RESCUE_PHOTOS files.
TIER1_BASE = ["gov_id", "proof_billing"]
MIN_RESCUE_PHOTOS = 3
# Tier-2 additions. `bai_cert` is deferrable at submit time via `bai_pending`.
NGO_EXTRA = ["sec_dti", "bai_cert"]


def required_doc_types(tier):
    """The full required doc-set for a tier. `rescue_photos` appears once here; its
    >=3 count is checked separately (a type is either required or not; the count is a
    completeness detail)."""
    base = TIER1_BASE + ["rescue_photos"]
    if tier == "registered_ngo":
        return base + NGO_EXTRA
    return base


def base_complete(present_types):
    """The tier-1 base is satisfied: both base docs present and enough rescue photos."""
    return (all(t in present_types for t in TIER1_BASE)
            and present_types.count("rescue_photos") >= MIN_RESCUE_PHOTOS)


def missing_docs(tier, present_types, bai_pending=False):
    """Required doc types absent from `present_types`, for the reviewer's line.

    `rescue_photos` counts as present only at >= MIN_RESCUE_PHOTOS. `bai_cert` is
    *deferred* (see `deferred_docs`), not missing, when `bai_pending` — so it is
    excluded here.
    """
    missing = []
    for t in required_doc_types(tier):
        if t == "rescue_photos":
            if present_types.count("rescue_photos") < MIN_RESCUE_PHOTOS:
                missing.append(t)
        elif t == "bai_cert" and bai_pending:
            continue  # deferred, not missing
        elif t not in present_types:
            missing.append(t)
    return missing


def deferred_docs(tier, present_types, bai_pending=False):
    """Required docs that are legitimately outstanding rather than missing — today only
    `bai_cert` under `bai_pending`, and only while it isn't already on file."""
    if (tier == "registered_ngo" and bai_pending
            and "bai_cert" not in present_types):
        return ["bai_cert"]
    return []


def review_checklist(tier, present_types):
    """The reviewer's read of an ALREADY-SUBMITTED request (US-R4). Returns
    (missing, deferred).

    `bai_pending` is never stored (it's a submit-time-only flag), but it doesn't need to
    be: the submit gate (`_shelter_doc_error`) never accepts a tier-2 request that is
    *genuinely* missing `bai_cert` — it 422s unless the applicant declared BAI pending.
    So a request that exists in the database with no `bai_cert` was necessarily deferred.
    We derive that here rather than storing a column, consistent with "verified is always
    derived" — an absent tier-2 `bai_cert` reads as deferred, a legitimate state, not a
    hole. Any *other* absent required doc is still surfaced as missing, so the line stays
    a real safety check the reviewer can trust over the gate.
    """
    bai_pending = tier == "registered_ngo" and "bai_cert" not in present_types
    return (missing_docs(tier, present_types, bai_pending),
            deferred_docs(tier, present_types, bai_pending))
