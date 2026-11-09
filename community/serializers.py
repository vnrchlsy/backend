from datetime import UTC

from rest_framework import serializers
from rest_framework.exceptions import APIException

from moderation.textfilter import ModeratedCharField

from .models import NeedCategory, NeedStatus, StoryType
from .needs import MAX_QTY


class BadCategory(APIException):
    """`funds` stays a valid enum value for rows that already have it, but no new or edited
    need may take it (a wishlist asks for things, not money). Raised as its own exception —
    a plain `ValidationError` would reach the envelope as the generic `invalid` code."""
    status_code = 400
    default_code = "bad_category"


def _refuse_funds(value):
    if value == NeedCategory.FUNDS:
        raise BadCategory({"category": ["A wishlist can't ask for funds."]})
    return value


class NeedCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    category = serializers.ChoiceField(choices=NeedCategory.choices)
    quantity_needed = serializers.IntegerField(min_value=1, max_value=MAX_QTY, default=1)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")

    def validate_category(self, value):
        return _refuse_funds(value)


class PledgeCreateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QTY, default=1)
    # R2 · for the owning shelter's eyes only; no public read and not /me/pledges returns it.
    note = serializers.CharField(max_length=280, required=False, allow_blank=True, default="")


class NeedPatchSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    quantity_needed = serializers.IntegerField(min_value=1, max_value=MAX_QTY, required=False)
    category = serializers.ChoiceField(choices=NeedCategory.choices, required=False)
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True)
    # The only client-driven status move is closing a need (open -> closed); fulfilled is
    # server-derived by the received-confirm writer, never set from the client.
    status = serializers.ChoiceField(choices=[NeedStatus.CLOSED], required=False)

    def validate_category(self, value):
        return _refuse_funds(value)


class ReceivedSerializer(serializers.Serializer):
    pledge_id = serializers.UUIDField()
    quantity_received = serializers.IntegerField(min_value=1, max_value=MAX_QTY)


class StoryPhotoSerializer(serializers.Serializer):
    file_url = serializers.CharField()
    is_primary = serializers.BooleanField(required=False, default=False)


def _own_story_photos(photos, account):
    """Stories review step 2 (ST2) · each photo must be THIS account's own `story_photo` upload
    (common/uploads.py), as every other photo surface requires. A story is on the one feed guests can
    read, so a foreign URL there would be fetched by every viewer's phone, and the erasure could not
    tell the author's files from a stranger's."""
    from common.uploads import own_upload_url_error
    for photo in photos:
        error = own_upload_url_error(photo["file_url"], account, "story_photo", noun="photo")
        if error:
            raise serializers.ValidationError(error)
    return photos


class StoryCreateSerializer(serializers.Serializer):
    caption = ModeratedCharField(required=False, allow_blank=True, default="")
    story_type = serializers.ChoiceField(choices=StoryType.choices, required=False)
    photos = StoryPhotoSerializer(many=True, required=False, default=list)
    adoption_listing_id = serializers.UUIDField(required=False, allow_null=True)
    rescue_case_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_photos(self, photos):
        return _own_story_photos(photos, self.context["request"].user)


# --- Stories review step 5 (ST6, ST16) · a story, as a contract -----------------------------------------------------------
# `_story_repr` built this by hand and the app kept three copies of its shape. These say what a story is, the feed and the detail
# return them, and community/tests/test_stories_contract.py holds the app's types (`Story`, `StoryPage`, `StoryLink`, `StoryAuthor`,
# `StoryPhoto` in mobile_app/src/community.ts) to the same field names.

class StoryAuthorSerializer(serializers.Serializer):
    name = serializers.CharField()
    city = serializers.CharField(allow_blank=True)


class StoryPhotoOutSerializer(serializers.Serializer):
    url = serializers.CharField()
    is_primary = serializers.BooleanField()


class StoryLinkSerializer(serializers.Serializer):
    """The adoption or rescue a story is about, for a viewer who may open it. `id` is the id its screen opens: a listing's
    `listing_id`, or a rescue's `report_id` (the public report screen, not the case)."""
    type = serializers.ChoiceField(choices=["adoption", "rescue"])
    id = serializers.UUIDField()


class StorySerializer(serializers.Serializer):
    story_id = serializers.UUIDField()
    author = StoryAuthorSerializer()
    story_type = serializers.ChoiceField(choices=StoryType.choices)
    caption = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    photos = StoryPhotoOutSerializer(many=True)
    primary_photo = serializers.CharField(allow_null=True)
    reaction_count = serializers.IntegerField()
    my_reaction = serializers.BooleanField()
    mine = serializers.BooleanField()
    # UTC, as stored, with a Z (DRF would render it in TIME_ZONE, Asia/Manila: the same instant, written +08:00).
    created_at = serializers.DateTimeField(default_timezone=UTC)
    link = StoryLinkSerializer(allow_null=True)


class StoryPageSerializer(serializers.Serializer):
    results = StorySerializer(many=True)
    next = serializers.CharField(allow_null=True)


class StoryPatchSerializer(serializers.Serializer):
    """Stories review step 6 · the one thing an author can change: the caption (through the word filter, and a blank one is fine: a story
    is a picture). The view refuses any other key."""
    caption = ModeratedCharField(allow_blank=True)


# --- IB26 · GET /me/impact: the response, as a contract ------------------------
# The payload was a hand-built dict, and the app read it as `any`. These say what it is, the view returns it, and
# community/tests/test_impact_contract.py holds the app's TypeScript types (`ImpactResponse`, `Impact`, `BadgeShape`,
# `BadgeProgress` in mobile_app/src/community.ts) to the same field names.

class BadgeProgressSerializer(serializers.Serializer):
    """How far along a badge is. `current` is honest and can pass `target`: a badge held after its stat fell reads
    earned with `current` below `target`."""
    current = serializers.IntegerField()
    target = serializers.IntegerField()


class ImpactCountsSerializer(serializers.Serializer):
    shifts_completed = serializers.IntegerField()
    rescues_helped = serializers.IntegerField()
    pets_rehomed = serializers.IntegerField()
    pledges_delivered = serializers.IntegerField()


class ImpactBadgeSerializer(serializers.Serializer):
    badge_code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    icon = serializers.CharField(allow_blank=True)
    criteria = serializers.CharField(allow_blank=True)
    earned = serializers.BooleanField()
    # UTC, as stored. DRF would render it in TIME_ZONE (Asia/Manila, +08:00): the same instant, but not what this said before.
    earned_at = serializers.DateTimeField(allow_null=True, default_timezone=UTC)
    progress = BadgeProgressSerializer(allow_null=True)


class MeImpactSerializer(serializers.Serializer):
    impact = ImpactCountsSerializer()
    badges = ImpactBadgeSerializer(many=True)
