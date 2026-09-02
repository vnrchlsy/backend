"""US-A2 · the ₱500 adoption-fee cap.

**Decided 2026-08-24: the cap applies to `community_rescue` (tier-1) shelters AND
Verified Members** (individual owners) — not just tier-1 shelters as originally scoped.
Same rationale either way (decision 4): an unregistered poster charging per animal at
volume edges into BAI-regulated trade, and an individual owner is exactly that
unregistered case. Only `registered_ngo` (tier-2) is uncapped. A validation rule, not a
DB constraint — it's a policy number, not a schema fact.
"""
from shelter.models import ShelterProfile

FEE_CAP = 500


def fee_cap_for(account):
    """The fee cap for `account`, or None if uncapped (tier-2 shelters only)."""
    profile = ShelterProfile.objects.filter(account=account).first()
    if profile is not None and profile.tier == "registered_ngo":
        return None
    return FEE_CAP
