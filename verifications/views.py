from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from verifications.models import (AccountCapability, VerificationDocument,
                                  VerificationRequest)
from verifications.serializers import VerificationSerializer


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
