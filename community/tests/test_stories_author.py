"""Stories review step 6 (ST7, SQ1) · an author can edit the caption of, delete, and find their own stories.

Before, `DELETE` and `PATCH /stories/{id}` were 405, there was no list of your own stories, and the author's hidden story was in no feed: a photo of someone's home
or child, once posted to a feed guests can read, could not be taken down by the person who posted it.

SQ1 (owner, 2026-11-09): a delete is SOFT for 30 days (gone from the feed, the detail and "your stories" at once, the row kept as moderation evidence) and then HARD,
with the photo files. `removed` is a status of its own so a moderation action can never put it back.
"""
import logging
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from community.models import StoryPhoto, StoryPost, StoryStatus
from community.serializers import StoryPageSerializer

URL = "/api/v1/stories"


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def own(acc, name="a.jpg"):
    return f"https://bkt.example/story_photo/{acc.pk}/{name}"


def _story(author, status=StoryStatus.PUBLISHED, caption="Home at last", created=None, removed_at=None, photos=1):
    s = StoryPost.objects.create(author_account=author, story_type="general", caption=caption, status=status, removed_at=removed_at)
    if created:
        StoryPost.objects.filter(pk=s.pk).update(created_at=created)
    for i in range(photos):
        StoryPhoto.objects.create(story=s, url=own(author, f"{s.pk}-{i}.jpg"), is_primary=(i == 0))
    return s


def _delete(client, story, acc=None):
    return client.delete(f"{URL}/{story.pk}", **(_hdr(acc) if acc else {}))


def _patch(client, story, body, acc=None):
    return client.patch(f"{URL}/{story.pk}", body, content_type="application/json", **(_hdr(acc) if acc else {}))


def _mine(client, acc, cursor=None):
    return client.get("/api/v1/me/stories" + (f"?cursor={cursor}" if cursor else ""), **_hdr(acc))


# ── delete ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_an_author_can_delete_their_story_and_it_is_gone_everywhere_at_once(client):
    me = AccountFactory()
    s = _story(me)
    assert _delete(client, s, me).status_code == 204
    assert str(s.pk) not in [r["story_id"] for r in client.get(URL).json()["results"]]
    assert client.get(f"{URL}/{s.pk}").status_code == 404
    assert client.get(f"{URL}/{s.pk}", **_hdr(me)).status_code == 404                    # the author too: it is deleted, not hidden
    assert str(s.pk) not in [r["story_id"] for r in _mine(client, me).json()["results"]]


@pytest.mark.django_db
def test_a_delete_is_soft_the_row_and_its_photos_are_kept_for_thirty_days(client):
    me = AccountFactory()
    s = _story(me, photos=2)
    before = timezone.now()
    _delete(client, s, me)
    s.refresh_from_db()
    assert s.status == StoryStatus.REMOVED and before <= s.removed_at <= timezone.now()
    assert s.photos.count() == 2                                                          # evidence, until the purge


@pytest.mark.django_db
def test_only_the_author_can_delete_and_anyone_else_is_told_it_is_not_there(client):
    s = _story(AccountFactory())
    assert _delete(client, s, AccountFactory()).status_code == 404                       # not 403: it does not confirm the story exists
    assert _delete(client, s).status_code == 401                                         # a guest
    s.refresh_from_db()
    assert s.status == StoryStatus.PUBLISHED


@pytest.mark.django_db
def test_deleting_twice_or_an_unknown_story_is_a_404(client):
    me = AccountFactory()
    s = _story(me)
    _delete(client, s, me)
    assert _delete(client, s, me).status_code == 404
    assert client.delete(f"{URL}/00000000-0000-0000-0000-000000000000", **_hdr(me)).status_code == 404


@pytest.mark.django_db
def test_an_author_can_delete_a_story_moderation_hid_and_it_cannot_come_back(client):
    from community.moderation import StoryNotHidden, restore_story
    me = AccountFactory()
    s = _story(me, status=StoryStatus.HIDDEN)
    assert _delete(client, s, me).status_code == 204
    s.refresh_from_db()
    assert s.status == StoryStatus.REMOVED
    with pytest.raises(StoryNotHidden):
        restore_story(s, by=None, reason="mistake")                                       # a restore must not undo a deletion
    s.refresh_from_db()
    assert s.status == StoryStatus.REMOVED


@pytest.mark.django_db
def test_a_moderation_takedown_cannot_turn_a_deleted_story_back_into_a_hidden_one(client):
    from moderation.targets import _hide_story
    me = AccountFactory()
    s = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now())
    assert _hide_story(s, reviewer=None, reason="") is False                              # nothing changed, so nothing is claimed or sent
    s.refresh_from_db()
    assert s.status == StoryStatus.REMOVED


@pytest.mark.django_db
def test_nobody_can_react_to_a_deleted_story(client):
    me, other = AccountFactory(), AccountFactory()
    s = _story(me)
    _delete(client, s, me)
    assert client.post(f"{URL}/{s.pk}/reactions", **_hdr(other)).status_code == 404


# ── edit the caption ────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_an_author_can_change_the_caption_and_the_feed_shows_it(client):
    me = AccountFactory()
    s = _story(me, caption="old")
    res = _patch(client, s, {"caption": "Meet Rex, six months on"}, me)
    assert res.status_code == 200 and res.json()["caption"] == "Meet Rex, six months on"
    assert next(r for r in client.get(URL).json()["results"] if r["story_id"] == str(s.pk))["caption"] == "Meet Rex, six months on"


@pytest.mark.django_db
def test_the_answer_to_an_edit_is_the_story_in_the_one_contract_shape(client):
    from community.serializers import StorySerializer
    me = AccountFactory()
    body = _patch(client, _story(me), {"caption": "x"}, me).json()
    assert StorySerializer(data=body).is_valid() and body["mine"] is True


@pytest.mark.django_db
def test_an_empty_caption_is_allowed_a_story_is_a_picture(client):
    me = AccountFactory()
    s = _story(me)
    assert _patch(client, s, {"caption": "   "}, me).json()["caption"] == ""


@pytest.mark.django_db
def test_an_edited_caption_goes_through_the_word_filter(client):
    me = AccountFactory()
    s = _story(me, caption="fine")
    res = _patch(client, s, {"caption": "what a fucker"}, me)
    assert res.status_code == 400 and res.json()["error"]["field"] == "caption"
    s.refresh_from_db()
    assert s.caption == "fine"


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"caption": None}, {"caption": "x", "story_type": "adoption"}, {"caption": "x", "photos": []},
                                  {"status": "published"}, {"caption": ["a"]}])
def test_only_the_caption_can_be_edited_and_it_must_be_a_string(client, body):
    me = AccountFactory()
    s = _story(me, caption="keep")
    res = _patch(client, s, body, me)
    assert res.status_code == 400
    s.refresh_from_db()
    assert s.caption == "keep" and s.story_type == "general" and s.status == StoryStatus.PUBLISHED


@pytest.mark.django_db
def test_nobody_but_the_author_can_edit(client):
    s = _story(AccountFactory(), caption="keep")
    assert _patch(client, s, {"caption": "mine now"}, AccountFactory()).status_code == 404
    assert _patch(client, s, {"caption": "mine now"}).status_code == 401
    s.refresh_from_db()
    assert s.caption == "keep"


@pytest.mark.django_db
def test_a_story_moderation_hid_cannot_be_edited_and_a_deleted_one_is_gone(client):
    me = AccountFactory()
    hidden = _story(me, status=StoryStatus.HIDDEN, caption="keep")
    res = _patch(client, hidden, {"caption": "changed"}, me)
    assert res.status_code == 409 and res.json()["error"]["code"] == "story_hidden"
    hidden.refresh_from_db()
    assert hidden.caption == "keep"
    gone = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now())
    assert _patch(client, gone, {"caption": "x"}, me).status_code == 404


# ── your stories ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_your_stories_are_yours_newest_first_with_hidden_ones_marked_and_deleted_ones_left_out(client):
    me, other = AccountFactory(), AccountFactory()
    now = timezone.now()
    newest = _story(me, created=now)
    hidden = _story(me, status=StoryStatus.HIDDEN, created=now - timedelta(days=1))
    oldest = _story(me, created=now - timedelta(days=2))
    _story(me, status=StoryStatus.REMOVED, removed_at=now, created=now - timedelta(days=3))
    _story(other)
    body = _mine(client, me).json()
    assert [r["story_id"] for r in body["results"]] == [str(newest.pk), str(hidden.pk), str(oldest.pk)]
    assert [r["status"] for r in body["results"]] == ["published", "hidden", "published"]
    assert all(r["mine"] for r in body["results"]) and body["next"] is None


@pytest.mark.django_db
def test_your_stories_page_by_cursor_like_the_wall(client):
    me = AccountFactory()
    now = timezone.now()
    made = [_story(me, created=now - timedelta(minutes=i)) for i in range(25)]
    first = _mine(client, me).json()
    assert len(first["results"]) == 20 and first["next"]
    second = _mine(client, me, first["next"]).json()
    assert [r["story_id"] for r in first["results"] + second["results"]] == [str(s.pk) for s in made] and second["next"] is None


@pytest.mark.django_db
def test_your_stories_answer_in_the_contract_shape_and_a_bad_cursor_is_400(client):
    me = AccountFactory()
    _story(me)
    assert StoryPageSerializer(data=_mine(client, me).json()).is_valid()
    assert _mine(client, me, "garbage").status_code == 400


@pytest.mark.django_db
def test_your_stories_need_you_to_be_signed_in_and_an_empty_list_is_an_empty_page(client):
    assert client.get("/api/v1/me/stories").status_code == 401
    assert _mine(client, AccountFactory()).json() == {"results": [], "next": None}


@pytest.mark.django_db
def test_a_blocked_or_suspended_viewer_context_does_not_hide_your_own_stories(client):
    me = AccountFactory()
    _story(me)
    from moderation.models import AccountBlock
    AccountBlock.objects.create(blocker=AccountFactory(), blocked=me)                    # someone blocked me: my own list is still mine
    assert len(_mine(client, me).json()["results"]) == 1


@pytest.mark.django_db
def test_a_page_of_your_stories_costs_a_fixed_number_of_queries(client, django_assert_max_num_queries):
    me = AccountFactory()
    for _ in range(20):
        _story(me)
    with django_assert_max_num_queries(10):
        _mine(client, me)


# ── the purge (SQ1: hard after thirty days) ─────────────────────────────────────────────────────
def _purge(now=None):
    from community.stories import purge_removed_stories
    return purge_removed_stories(now=now)


@pytest.mark.django_db
def test_a_story_deleted_thirty_days_ago_is_removed_for_good_with_its_photos_and_files():
    me = AccountFactory()
    old = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now() - timedelta(days=31), photos=2)
    urls = set(old.photos.values_list("url", flat=True))
    with mock.patch("community.stories.delete_object") as delete_object:
        assert _purge() == 1
    assert not StoryPost.objects.filter(pk=old.pk).exists() and not StoryPhoto.objects.filter(story_id=old.pk).exists()
    assert {c.args[0] for c in delete_object.call_args_list} == urls


@pytest.mark.django_db
def test_a_story_deleted_recently_is_kept_and_so_is_everything_that_was_not_deleted():
    me = AccountFactory()
    recent = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now() - timedelta(days=29))
    live, hidden = _story(me), _story(me, status=StoryStatus.HIDDEN)
    with mock.patch("community.stories.delete_object") as delete_object:
        assert _purge() == 0
    assert StoryPost.objects.filter(pk__in=[recent.pk, live.pk, hidden.pk]).count() == 3
    delete_object.assert_not_called()


@pytest.mark.django_db
def test_the_purge_never_deletes_a_file_that_is_not_the_authors_own_upload():
    me = AccountFactory()
    old = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now() - timedelta(days=40), photos=0)
    StoryPhoto.objects.create(story=old, url="https://bkt.example/story_photo/someone-else/x.jpg")     # a legacy row, any URL
    StoryPhoto.objects.create(story=old, url=own(me, "mine.jpg"))
    with mock.patch("community.stories.delete_object") as delete_object:
        _purge()
    assert {c.args[0] for c in delete_object.call_args_list} == {own(me, "mine.jpg")}


@pytest.mark.django_db
def test_a_storage_error_never_stops_the_purge_the_rows_go_and_the_key_is_logged(caplog):
    me = AccountFactory()
    a = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now() - timedelta(days=40))
    b = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now() - timedelta(days=41))
    with caplog.at_level(logging.WARNING, logger="kupkop.storage"), \
            mock.patch("community.stories.delete_object", side_effect=RuntimeError("S3 is down")) as delete_object:
        assert _purge() == 2
    assert not StoryPost.objects.filter(pk__in=[a.pk, b.pk]).exists()                  # the person's right is not held hostage by a bucket
    assert delete_object.call_count == 2
    assert "could not delete" in caplog.text and "story_photo/" in caplog.text           # the key, so an orphan can be found by hand
    assert "bkt.example" not in caplog.text                                              # never the URL (it can carry a host and a signature)


@pytest.mark.django_db
def test_the_purge_is_idempotent_and_takes_an_explicit_clock():
    me = AccountFactory()
    old = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now() - timedelta(days=31))
    with mock.patch("community.stories.delete_object"):
        assert _purge() == 1 and _purge() == 0
    again = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now())
    with mock.patch("community.stories.delete_object"):
        assert _purge(now=timezone.now() + timedelta(days=31)) == 1
    assert not StoryPost.objects.filter(pk__in=[old.pk, again.pk]).exists()


@pytest.mark.django_db
def test_the_command_runs_the_purge():
    from django.core.management import call_command
    me = AccountFactory()
    old = _story(me, status=StoryStatus.REMOVED, removed_at=timezone.now() - timedelta(days=31))
    with mock.patch("community.stories.delete_object"):
        call_command("purge_removed_stories")
    assert not StoryPost.objects.filter(pk=old.pk).exists()
