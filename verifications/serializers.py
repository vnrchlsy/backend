from rest_framework import serializers


class PresignSerializer(serializers.Serializer):
    # `purpose` stays a plain CharField (not ChoiceField) — an unknown purpose gets the
    # story's own documented `422 purpose_unknown`, not a generic field-validation 400.
    purpose = serializers.CharField()
    content_type = serializers.CharField()


class DocumentSerializer(serializers.Serializer):
    doc_type = serializers.CharField()
    file_url = serializers.CharField()


class VerificationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["rescuer", "shelter_org", "provider"])
    social_proof_url = serializers.CharField(required=False, allow_blank=True)
    consent_version = serializers.CharField(required=False, allow_blank=True)
    bai_pending = serializers.BooleanField(required=False, default=False)   # US-C1: submit SEC now, BAI later
    documents = DocumentSerializer(many=True)
