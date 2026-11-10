"""Stories review steps 14 and 15 (ST20, ST21) · the lifecycle leaves timestamps and a notice, and the city filter forgives spelling.

Step 14: `story_post` gains `hidden_at` and `restored_at`; a restore tells the author their story is back (a takedown already tells them it
was hidden, since step 9); and `restore_story`'s docstring no longer says the author is not told.
Step 15: `?city=` matches case-insensitively and with or without a trailing "City", through `common.cities`; `.distinct()` is gone because
`uq_address_one_primary` holds one primary per account.
"""
import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.models import Address
from community.models import StoryPost, StoryStatus
from moderation.actions import resolve_flag
from moderation.models import FlagStatus, ModerationFlag
from notifications.models import Notification


def _story(author=None, status=StoryStatus.PUBLISHED):
    return StoryPost.objects.create(author_account=author or AccountFactory(), story_type="general", caption="x", status=status)


def _acct_in(city):
    acc = AccountFactory()
    Address.objects.create(account=acc, city=city, is_primary=True)
    return acc


def _takedown(story):
    flag = ModerationFlag.objects.create(reporter_account=AccountFactory(), target_type="story", target_id=story.pk, reason="x", status="open")
    resolve_flag(flag, AccountFactory(), FlagStatus.ACTIONED, reason_code="spam_scam")


# ---- step 15 · the city filter ------------------------------------------------------------------------------------------------
@pytest.mark.django_db
@pytest.mark.parametrize("asked", ["Marikina", "marikina", "MARIKINA", "Marikina City", "marikina  city", " Marikina "])
def test_the_city_filter_ignores_case_and_a_trailing_city(client, asked):
    mine = _story(author=_acct_in("Marikina"))
    _story(author=_acct_in("Pasig"))
    res = client.get("/api/v1/stories", {"city": asked})
    assert [s["story_id"] for s in res.json()["results"]] == [str(mine.pk)]


@pytest.mark.django_db
def test_a_stored_city_spelled_with_city_matches_a_plain_ask(client):
    mine = _story(author=_acct_in("Marikina City"))
    res = client.get("/api/v1/stories", {"city": "marikina"})
    assert [s["story_id"] for s in res.json()["results"]] == [str(mine.pk)]


@pytest.mark.django_db
def test_a_blank_city_does_not_filter(client):
    _story(author=_acct_in("Marikina"))
    _story(author=_acct_in("Pasig"))
    for blank in ("", "   "):
        assert len(client.get("/api/v1/stories", {"city": blank}).json()["results"]) == 2


@pytest.mark.django_db
def test_a_story_is_listed_once_without_distinct(client):
    # An author with a second, non-primary address in the same city would have doubled the row under a join without `is_primary`.
    author = _acct_in("Marikina")
    Address.objects.create(account=author, city="Marikina", is_primary=False)
    _story(author=author)
    res = client.get("/api/v1/stories", {"city": "Marikina"})
    assert len(res.json()["results"]) == 1


@pytest.mark.django_db
def test_the_city_query_does_not_use_distinct():
    import inspect

    from community import views
    src = inspect.getsource(views.StoriesView.get)
    assert "city" in src and ".distinct()" not in src


# ---- step 14 · the timestamps -------------------------------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_new_story_has_neither_timestamp():
    s = _story()
    assert s.hidden_at is None and s.restored_at is None


@pytest.mark.django_db
def test_a_takedown_stamps_hidden_at_once():
    s = _story()
    before = timezone.now()
    _takedown(s)
    s.refresh_from_db()
    assert s.status == StoryStatus.HIDDEN and s.hidden_at is not None and s.hidden_at >= before
    first = s.hidden_at
    _takedown(s)                         # a second flag on an already hidden story changes nothing
    s.refresh_from_db()
    assert s.hidden_at == first


@pytest.mark.django_db
def test_a_restore_stamps_restored_at_and_a_second_takedown_restamps_hidden_at():
    from community.moderation import restore_story
    s = _story()
    _takedown(s)
    s.refresh_from_db()
    hidden_first = s.hidden_at
    restore_story(s, AccountFactory(), "in error")
    s.refresh_from_db()
    assert s.status == StoryStatus.PUBLISHED and s.restored_at is not None and s.restored_at >= hidden_first
    _takedown(s)
    s.refresh_from_db()
    assert s.hidden_at >= s.restored_at          # the history is the latest hide and the latest restore


@pytest.mark.django_db
def test_an_authors_own_delete_stamps_neither():
    s = _story()
    StoryPost.objects.filter(pk=s.pk).update(status=StoryStatus.REMOVED)
    s.refresh_from_db()
    assert s.hidden_at is None and s.restored_at is None


# ---- step 14 · the notice -----------------------------------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_restore_tells_the_author_and_links_to_the_story():
    from community.moderation import restore_story
    author = AccountFactory()
    s = _story(author=author, status=StoryStatus.HIDDEN)
    restore_story(s, AccountFactory(), "Flagged in error.")
    note = Notification.objects.get(account=author, type="story_restored")
    assert note.data == {"story_id": str(s.pk)}
    assert "back" in note.title.lower() or "back" in note.body.lower()
    assert "Flagged in error" not in note.body             # the staff reason is internal, never sent


@pytest.mark.django_db
def test_restoring_a_story_that_is_not_hidden_tells_nobody():
    from community.moderation import StoryNotHidden, restore_story
    author = AccountFactory()
    s = _story(author=author)
    with pytest.raises(StoryNotHidden):
        restore_story(s, AccountFactory(), "x")
    assert not Notification.objects.filter(account=author, type="story_restored").exists()


@pytest.mark.django_db
def test_the_notice_type_is_registered_with_a_story_link():
    from notifications.types import REGISTRY, is_registered
    assert is_registered("story_restored") and REGISTRY["story_restored"].deep_link == "kupkop://stories/{story_id}"


def test_the_restore_docstring_no_longer_says_the_author_is_not_told():
    from community.moderation import restore_story
    doc = restore_story.__doc__
    assert doc and "is not told" not in doc and "a takedown does not tell them" not in doc
