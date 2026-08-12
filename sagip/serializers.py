from rest_framework import serializers

from sagip.models import Species, StrayCondition


class PhotoSerializer(serializers.Serializer):
    file_url = serializers.CharField()


class ReportCreateSerializer(serializers.Serializer):
    species = serializers.ChoiceField(choices=[c.value for c in Species])
    condition = serializers.ChoiceField(choices=[c.value for c in StrayCondition])
    notes = serializers.CharField(required=False, allow_blank=True)
    is_anonymous = serializers.BooleanField(required=False, default=False)
    # The one precise-GPS surface in the app (decision 11) — a real point, validated to
    # earth-plausible ranges. geom is NOT NULL, so both are required.
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    location_text = serializers.CharField(required=False, allow_blank=True, max_length=160)
    photos = PhotoSerializer(many=True, required=False)
