from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from verifications.models import (AccountCapability, VerificationDocument,
                                  VerificationRequest)
from verifications.serializers import VerificationSerializer

# The tier-1 base document set (§3.5). A community rescue submits exactly this;
# a registered NGO must include it too, plus the NGO papers below.
TIER1_BASE = ["gov_id", "proof_billing"]
MIN_RESCUE_PHOTOS = 3


def _shelter_doc_error(tier, docs, bai_pending):
    """Server-derived doc check (never trust the client's list). Returns an
    (http_status, body) tuple to reject, or None if the set satisfies the tier."""
    types = [d["doc_type"] for d in docs]
    base_ok = all(t in types for t in TIER1_BASE) and types.count("rescue_photos") >= MIN_RESCUE_PHOTOS
    if tier == "registered_ngo":
        # Rule 5: tier-1 base must be present before any tier-2 evidence is accepted.
        if not base_ok:
            return 409, {"error": {"code": "tier1_incomplete",
                                   "message": "Submit the base (tier-1) documents first"}}
        missing = "sec_dti" not in types or (not bai_pending and "bai_cert" not in types)
        if missing:
            required = ["gov_id", "proof_billing", "rescue_photos", "sec_dti"]
            if not bai_pending:
                required.append("bai_cert")
            return 422, {"error": {"code": "missing_docs", "message": "Required documents missing",
                                   "details": {"required": required, "min_photos": MIN_RESCUE_PHOTOS}}}
        return None
    # community_rescue (tier 1)
    if not base_ok:
        return 422, {"error": {"code": "missing_docs", "message": "Required documents missing",
                               "details": {"required": ["gov_id", "proof_billing", "rescue_photos"],
                                           "min_photos": MIN_RESCUE_PHOTOS}}}
    return None


class PresignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # dev stub: no S3 in this slice; returns a placeholder the client can submit
        key = f"dev-uploads/{request.user.account_id}/{timezone.now().timestamp()}"
        return Response({"upload_url": "https://example.invalid/dev-upload",
                         "fields": {}, "file_url": f"https://example.invalid/{key}"})


class VerificationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    CAP_FOR_TYPE = {"rescuer": "rescuer", "provider": "provider"}

    def post(self, request):
        s = VerificationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        if not data.get("consent_version"):
            return Response({"error": {"code": "consent_missing",
                                       "message": "Consent is required to submit documents"}},
                            status=422)
        if data["type"] == "shelter_org":
            if request.user.account_type != "shelter":
                return Response({"error": {"code": "not_shelter",
                                           "message": "Only shelter accounts submit org verification"}},
                                status=403)
            from shelter.models import ShelterProfile
            profile = ShelterProfile.objects.filter(account=request.user).first()
            if profile is None:
                return Response({"error": {"code": "no_profile",
                                           "message": "Set up the shelter profile first"}}, status=409)
            # Required set is derived from the stored tier, server-side (§3.5) — the
            # client's document list is never trusted to declare which tier it is.
            err = _shelter_doc_error(profile.tier, data["documents"], data.get("bai_pending", False))
            if err is not None:
                return Response(err[1], status=err[0])
        with transaction.atomic():
            vr = VerificationRequest.objects.create(
                account=request.user, type=data["type"], status="pending",
                social_proof_url=data.get("social_proof_url", ""),
                consent_at=timezone.now(), consent_version=data["consent_version"])
            for doc in data["documents"]:
                VerificationDocument.objects.create(verification=vr, doc_type=doc["doc_type"],
                                                    file_url=doc["file_url"], status="pending")
            cap = self.CAP_FOR_TYPE.get(data["type"])
            if cap:
                AccountCapability.objects.get_or_create(
                    account=request.user, capability=cap, defaults={"status": "pending"})
        return Response({"verification_id": str(vr.verification_id), "status": "pending"},
                        status=201)
