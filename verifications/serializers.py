from rest_framework import serializers


class DocumentSerializer(serializers.Serializer):
    doc_type = serializers.CharField()
    file_url = serializers.CharField()


class VerificationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["rescuer", "shelter_org", "provider"])
    social_proof_url = serializers.CharField(required=False, allow_blank=True)
    consent_version = serializers.CharField(required=False, allow_blank=True)
    documents = DocumentSerializer(many=True)
