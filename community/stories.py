"""Stories review steps 1 and 3 (library docs/superpowers/specs/2026-11-09-stories-review.md) · the one writer
for a new story, as `community/needs.py` is for the wishlist (D-S6-7).

- ST1 · the story and its photos commit together or not at all, and `story_posted` is emitted only after the
  commit, so a failed photo never leaves a published story with photos missing, and the event never counts a
  story that does not exist.
- ST3 / ST4 · a link is resolved here, not left to the foreign key (an unknown id was a 500), and it must be
  earned: the author is the poster or the adopter of a listing that was adopted, or the claimer or the reporter
  of a rescue that resolved. The type comes from the link; "adoption" and "rescue" are never the client's claim.
- SQ3 · one story per author per link, checked here and held by the two partial unique constraints.

The photo rule (each must be this account's own `story_photo` upload, ST2) is the serializer's, beside the other
field checks.
"""
from django.db import IntegrityError, transaction

from common.analytics import emit

from .models import StoryPhoto, StoryPost, StoryType


class StoryError(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


_EXISTS = StoryError("story_exists", "You've already shared a story about this.", 409)


def _listing_link(author, listing_id):
    from listings.models import AdoptionListing, ListingStatus
    listing = AdoptionListing.objects.filter(pk=listing_id).only("posted_by_id", "adopted_by_account_id",
                                                                 "status").first()
    if listing is None:
        raise StoryError("link_not_found", "We couldn't find that adoption.", 422)
    if author.pk not in (listing.posted_by_id, listing.adopted_by_account_id):
        raise StoryError("not_your_story", "Only the people in an adoption can share its story.", 403)
    if listing.status != ListingStatus.ADOPTED:
        raise StoryError("link_not_eligible", "You can share this story once the adoption is complete.", 422)
    return {"adoption_listing_id": listing.pk}, StoryType.ADOPTION


def _case_link(author, case_id):
    from sagip.models import RescueCase
    case = RescueCase.objects.select_related("report").filter(pk=case_id).first()
    if case is None:
        raise StoryError("link_not_found", "We couldn't find that rescue.", 422)
    if author.pk not in (case.claimed_by_account_id, case.report.reporter_account_id):
        raise StoryError("not_your_story", "Only the people in a rescue can share its story.", 403)
    if case.resolved_at is None or case.expired_at is not None:
        raise StoryError("link_not_eligible", "You can share this story once the rescue is resolved.", 422)
    return {"rescue_case_id": case.pk}, StoryType.RESCUE


def _resolve_link(author, story_type, adoption_listing_id, rescue_case_id):
    if adoption_listing_id and rescue_case_id:
        raise StoryError("one_link_only", "A story can be about one adoption or one rescue, not both.", 422)
    if adoption_listing_id:
        return _listing_link(author, adoption_listing_id)
    if rescue_case_id:
        return _case_link(author, rescue_case_id)
    if story_type in (StoryType.ADOPTION, StoryType.RESCUE):
        raise StoryError("link_required", "An adoption or rescue story needs the adoption or rescue it is about.", 422)
    return {}, StoryType.GENERAL


def create_story(author, *, photos, caption="", story_type=None, adoption_listing_id=None, rescue_case_id=None):
    """Write one story and its photos. Raises `StoryError` for a link that is unknown, not the author's, not yet
    eligible, or already has the author's story."""
    link, derived_type = _resolve_link(author, story_type, adoption_listing_id, rescue_case_id)
    if link and StoryPost.objects.filter(author_account=author, **link).exists():
        raise _EXISTS
    try:
        with transaction.atomic():
            story = StoryPost.objects.create(author_account=author, caption=caption, story_type=derived_type, **link)
            for photo in photos:
                StoryPhoto.objects.create(story=story, url=photo["file_url"],
                                          is_primary=photo.get("is_primary", False))
    except IntegrityError:
        if link and StoryPost.objects.filter(author_account=author, **link).exists():
            raise _EXISTS from None           # a racing post on the same link won (uq_story_author_*)
        raise
    transaction.on_commit(lambda: emit("story_posted", story_type=derived_type))
    return story
