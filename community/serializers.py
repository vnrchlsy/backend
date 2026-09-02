from rest_framework import serializers

from .models import NeedCategory


class NeedCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    category = serializers.ChoiceField(choices=NeedCategory.choices)
    quantity_needed = serializers.IntegerField(min_value=1, default=1)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class PledgeCreateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, default=1)


class ReceivedSerializer(serializers.Serializer):
    pledge_id = serializers.UUIDField()
    quantity_received = serializers.IntegerField(min_value=1)
