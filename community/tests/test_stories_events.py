"""Stories review step 10 (ST18) · the telemetry that lets the success wall be measured.

Before, the only events were `story_posted {story_type}` and `story_reacted {story_type}`: net reactions, the conversion of the prompts of §5.7, why posts fail, and reach were all
unknowable. The analytics layer (common/analytics.py, D-S6-6) is server-side and account-free, and a client analytics SDK is deliberately left to Phase 2 (D-S7-3), so everything here is
a server event with coarse dimensions: never an account id, a caption, a URL, or a story id. Every event is emitted only for what actually happened, and after the commit.
"""
import json
import logging
import uuid

import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from community.models import StoryPhoto, StoryPost, StoryReaction, StoryStatus
from listings.models import AdoptionListing, ListingStatus

URL = "/api/v1/stories"


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def own(acc, name="a.jpg"):
    return f"https://bkt.example/story_photo/{acc.pk}/{name}"


def _events(caplog, name=None):
    out = [json.loads(r.getMessage()) for r in caplog.records if r.name == "kupkop.analytics"]
    return [e for e in out if name is None or e["event"] == name]


def _story(author, status=StoryStatus.PUBLISHED, photos=1):
    s = StoryPost.objects.create(author_account=author, story_type="general", caption="x", status=status)
    for i in range(photos):
        StoryPhoto.objects.create(story=s, url=own(author, f"{s.pk}-{i}.jpg"), is_primary=(i == 0), position=i)
    return s


@pytest.fixture
def logged(caplog):
    """Capture analytics lines. Every test here runs in a REAL transaction (transaction=True), so an on-commit event fires when the request commits, as in production."""
    with caplog.at_level(logging.INFO, logger="kupkop.analytics"):
        yield caplog


def _post(client, acc, **body):
    body.setdefault("photos", [{"file_url": own(acc)}])
    return client.post(URL, body, content_type="application/json", **_hdr(acc))


def _no_pii(event, *accounts):
    text = json.dumps(event)
    for acc in accounts:
        assert str(acc.pk) not in text and acc.email not in text and acc.display_name not in text
    assert not {"account_id", "account", "story_id", "caption", "url", "photos", "email"} & set(event)


# ── story_posted: where from, linked or not, how many photos ────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_story_posted_says_where_it_came_from_whether_it_is_linked_and_how_many_photos(client, logged):
    me = AccountFactory()
    _post(client, me, source="feed", photos=[{"file_url": own(me, f"{i}.jpg")} for i in range(3)])
    (e,) = _events(logged, "story_posted")
    assert (e["story_type"], e["source"], e["linked"], e["photo_count"]) == ("general", "feed", False, 3)
    _no_pii(e, me)


@pytest.mark.django_db(transaction=True)
def test_a_linked_story_from_the_adoption_prompt_says_so(client, logged):
    poster = AccountFactory()
    listing = AdoptionListing.objects.create(posted_by=poster, name="B", species="dog", city="Marikina", adoption_fee="0", status=ListingStatus.ADOPTED)
    _post(client, poster, source="adoption_cta", adoption_listing_id=str(listing.pk))
    (e,) = _events(logged, "story_posted")
    assert (e["story_type"], e["source"], e["linked"]) == ("adoption", "adoption_cta", True)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("source", ["feed", "adoption_cta", "poster_prompt", "rescue_prompt"])
def test_every_entry_point_the_app_has_is_a_known_source(client, logged, source):
    """Stories review step 11 · the poster's and the rescuer's prompts are entry points too; this list must grow with the app's (see STORY_SOURCES)."""
    me = AccountFactory()
    _post(client, me, source=source)
    (e,) = _events(logged, "story_posted")
    assert e["source"] == source


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("sent", [None, "", "  ", "nonsense", "FEED", "a" * 200, "x; drop table"])
def test_a_source_that_is_missing_or_not_one_we_know_is_unknown_and_never_an_error(client, logged, sent):
    me = AccountFactory()
    body = {} if sent is None else {"source": sent}
    assert _post(client, me, **body).status_code == 201
    (e,) = _events(logged, "story_posted")
    assert e["source"] == "unknown" and "nonsense" not in json.dumps(e)                    # free text never reaches the log


@pytest.mark.django_db(transaction=True)
def test_a_source_that_is_not_text_is_a_400_like_any_other_bad_field(client, logged):
    me = AccountFactory()
    assert _post(client, me, source={"a": 1}).status_code == 400
    assert _events(logged, "story_posted") == []


# ── story_post_refused: why posts fail ──────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("body,reason", [
    ({"photos": []}, "photo_required"),
    ({"caption": "a" * 2001}, "invalid_caption"),
    ({"caption": "what a fucker"}, "invalid_caption"),                                        # the word filter shares the field's reason
    ({"photos": [{"file_url": "https://evil.example/x.jpg"}]}, "invalid_photos"),
    ({"story_type": "adoption"}, "link_required"),
    ({"adoption_listing_id": str(uuid.uuid4())}, "link_not_found"),
    ({"story_type": "nonsense"}, "invalid_story_type"),
])
def test_a_refused_post_says_why_with_a_coarse_reason(client, logged, body, reason):
    me = AccountFactory()
    res = _post(client, me, **body) if "photos" in body else _post(client, me, **body)
    assert res.status_code in (400, 422)
    (e,) = _events(logged, "story_post_refused")
    assert e["reason"] == reason
    _no_pii(e, me)
    assert _events(logged, "story_posted") == []


@pytest.mark.django_db(transaction=True)
def test_a_second_story_on_a_link_is_refused_with_its_reason(client, logged):
    poster = AccountFactory()
    listing = AdoptionListing.objects.create(posted_by=poster, name="B", species="dog", city="Marikina", adoption_fee="0", status=ListingStatus.ADOPTED)
    _post(client, poster, adoption_listing_id=str(listing.pk))
    _post(client, poster, adoption_listing_id=str(listing.pk), photos=[{"file_url": own(poster, "b.jpg")}])
    assert [e["reason"] for e in _events(logged, "story_post_refused")] == ["story_exists"]


@pytest.mark.django_db(transaction=True)
def test_a_good_post_emits_no_refusal_and_a_refusal_emits_no_post(client, logged):
    me = AccountFactory()
    _post(client, me)
    assert _events(logged, "story_post_refused") == [] and len(_events(logged, "story_posted")) == 1


# ── reactions: net reactions are derivable ──────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_un_reacting_emits_story_unreacted_only_when_a_reaction_was_removed(client, logged):
    me, s = AccountFactory(), _story(AccountFactory())
    StoryReaction.objects.create(story=s, account=me)
    client.delete(f"{URL}/{s.pk}/reactions", **_hdr(me))
    client.delete(f"{URL}/{s.pk}/reactions", **_hdr(me))                                       # nothing left to remove: nothing happened
    (e,) = _events(logged, "story_unreacted")
    assert e["story_type"] == "general"
    _no_pii(e, me)


@pytest.mark.django_db(transaction=True)
def test_reacting_twice_emits_story_reacted_once_and_un_reacting_a_hidden_story_emits_nothing(client, logged):
    me, s = AccountFactory(), _story(AccountFactory())
    client.post(f"{URL}/{s.pk}/reactions", **_hdr(me))
    client.post(f"{URL}/{s.pk}/reactions", **_hdr(me))
    assert len(_events(logged, "story_reacted")) == 1
    hidden = _story(AccountFactory(), status=StoryStatus.HIDDEN)
    StoryReaction.objects.create(story=hidden, account=me)
    client.delete(f"{URL}/{hidden.pk}/reactions", **_hdr(me))
    assert _events(logged, "story_unreacted") == []


# ── the author's own controls ───────────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_editing_a_caption_and_deleting_a_story_each_emit_one_event(client, logged):
    me = AccountFactory()
    s = _story(me)
    client.patch(f"{URL}/{s.pk}", {"caption": "new"}, content_type="application/json", **_hdr(me))
    client.delete(f"{URL}/{s.pk}", **_hdr(me))
    (edited,), (deleted,) = _events(logged, "story_edited"), _events(logged, "story_deleted")
    assert deleted["story_type"] == "general" and deleted["was_hidden"] is False
    _no_pii(edited, me)
    _no_pii(deleted, me)


@pytest.mark.django_db(transaction=True)
def test_deleting_a_story_moderation_hid_says_so_and_a_refused_edit_or_delete_emits_nothing(client, logged):
    me, other = AccountFactory(), AccountFactory()
    hidden = _story(me, status=StoryStatus.HIDDEN)
    client.patch(f"{URL}/{hidden.pk}", {"caption": "x"}, content_type="application/json", **_hdr(me))          # 409
    client.delete(f"{URL}/{_story(me).pk}", **_hdr(other))                                                      # 404
    assert _events(logged, "story_edited") == [] and _events(logged, "story_deleted") == []
    client.delete(f"{URL}/{hidden.pk}", **_hdr(me))
    assert _events(logged, "story_deleted")[0]["was_hidden"] is True


@pytest.mark.django_db(transaction=True)
def test_the_purge_emits_one_event_with_a_count_and_none_when_nothing_was_purged(logged):
    from datetime import timedelta
    from unittest import mock

    from community.stories import purge_removed_stories
    me = AccountFactory()
    for _ in range(3):
        s = _story(me, status=StoryStatus.REMOVED)
        StoryPost.objects.filter(pk=s.pk).update(removed_at=timezone.now() - timedelta(days=31))
    with mock.patch("community.stories.delete_object"):
        assert purge_removed_stories() == 3
        assert purge_removed_stories() == 0
    (e,) = _events(logged, "story_purged")
    assert e["count"] == 3


# ── story_viewed: reach ─────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_opening_a_story_emits_one_view_that_says_whether_a_member_or_a_guest_looked(client, logged):
    s = _story(AccountFactory())
    client.get(f"{URL}/{s.pk}")
    client.get(f"{URL}/{s.pk}", **_hdr(AccountFactory()))
    guest, member = _events(logged, "story_viewed")
    assert (guest["viewer"], member["viewer"]) == ("guest", "member") and guest["story_type"] == "general"
    _no_pii(guest)
    _no_pii(member)


@pytest.mark.django_db(transaction=True)
def test_an_authors_own_look_a_missing_story_and_a_hidden_one_are_not_views(client, logged):
    me = AccountFactory()
    mine, hidden = _story(me), _story(AccountFactory(), status=StoryStatus.HIDDEN)
    client.get(f"{URL}/{mine.pk}", **_hdr(me))
    client.get(f"{URL}/{hidden.pk}")
    client.get(f"{URL}/{uuid.uuid4()}")
    assert _events(logged, "story_viewed") == []


@pytest.mark.django_db(transaction=True)
def test_the_feed_is_not_counted_as_a_view_of_each_story(client, logged):
    _story(AccountFactory())
    client.get(URL)
    assert _events(logged, "story_viewed") == []


# ── an analytics failure never breaks the request ───────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_a_broken_logger_never_fails_a_post_a_react_or_a_view(client):
    from unittest import mock
    me, s = AccountFactory(), _story(AccountFactory())
    with mock.patch("common.analytics.logger.info", side_effect=RuntimeError("log pipe closed")):
        assert _post(client, me).status_code == 201
        assert client.post(f"{URL}/{s.pk}/reactions", **_hdr(me)).status_code == 200
        assert client.get(f"{URL}/{s.pk}").status_code == 200
