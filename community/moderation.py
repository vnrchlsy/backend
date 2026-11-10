"""Review step 4 · the staff restore for a story a moderation takedown hid. The story counterpart of
listings/moderation.py and sagip/moderation.py: hide, never delete, and a mistaken takedown can be undone.

Only a moderation takedown ever sets a story `hidden` (`moderation.targets._hide_story`), so restoring one cannot
override an author's own choice."""
from django.db import transaction
from django.utils import timezone

from community.models import StoryPost, StoryStatus


class StoryNotHidden(Exception):
    """`restore_story` on a story no takedown is holding."""


@transaction.atomic
def restore_story(story, by, reason):
    """Put a hidden story back in the feed. It clears the hidden state, stamps `restored_at`, and tells the author it is back (stories review
    step 14: a takedown tells them it was hidden, so a mistaken one has to tell them it was undone). The staff reason is internal and is never in
    the notice. The flags about it stay as the audit trail. Raises `StoryNotHidden` when there is nothing to restore."""
    from notifications.service import notify
    locked = StoryPost.objects.select_for_update().filter(pk=story.pk).first()
    if locked is None or locked.status != StoryStatus.HIDDEN:
        raise StoryNotHidden()
    locked.status = StoryStatus.PUBLISHED
    locked.restored_at = timezone.now()
    locked.save(update_fields=["status", "restored_at"])
    story.status, story.restored_at = StoryStatus.PUBLISHED, locked.restored_at
    notify(locked.author_account, "story_restored", title="Your story is back",
           body="Our moderators looked again and put your story back on the wall. Thanks for your patience.",
           data={"story_id": str(locked.pk)})
    return story
