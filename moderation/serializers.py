from rest_framework import serializers

from moderation.models import FlagTarget


class ModerationFlagCreateSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=FlagTarget.values)
    target_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=2000)
