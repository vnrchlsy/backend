from rest_framework import serializers

from volunteer.models import VolunteerType


class ShiftCreateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=VolunteerType.values)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    capacity = serializers.IntegerField(min_value=1)


class ShiftPatchSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=VolunteerType.values, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    capacity = serializers.IntegerField(min_value=1, required=False)
