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


class SignupCreateSerializer(serializers.Serializer):
    # Two independent consents. The waiver is required (checked in the view so it returns the
    # story's documented `422 waiver_required`, not a generic field error); contact-sharing is
    # optional and defaults to declined — a §12.5 exception must be opted INTO.
    waiver_accepted = serializers.BooleanField()
    contact_share_consent = serializers.BooleanField(required=False, default=False)


class AttendanceSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["completed", "no_show"])
