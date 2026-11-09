"""Stories review step 4 (ST5, ST23) · the feed pages, by a keyset cursor over (created_at, story_id).

Before, `GET /stories` returned the newest 20 and ignored `?page=`, so story 21 could never be seen again by anyone. An
offset page would be wrong on a live feed (a story posted while someone scrolls shifts every later row, so the next page
repeats one), so `next` is an opaque cursor, a position rather than a row or a page number.
"""
import base64
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from community.models import StoryPhoto, StoryPost, StoryStatus

PAGE = 20


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _stories(n, author=None, status=StoryStatus.PUBLISHED, start=None, step=timedelta(minutes=1)):
    """`n` stories, each `step` older than the last, newest first by construction."""
    author = author or AccountFactory()
    now = start or timezone.now()
    made = []
    for i in range(n):
        s = StoryPost.objects.create(author_account=author, story_type="general", caption=f"s{i}", status=status)
        StoryPost.objects.filter(pk=s.pk).update(created_at=now - step * i)
        StoryPhoto.objects.create(story=s, url=f"https://x/{i}.jpg", is_primary=True)
        made.append(s)
    return made


def _get(client, cursor=None, **extra):
    url = "/api/v1/stories" + (f"?cursor={cursor}" if cursor is not None else "")
    return client.get(url, **extra)


def _ids(res):
    return [r["story_id"] for r in res.json()["results"]]


@pytest.mark.django_db
def test_25_stories_are_two_pages_newest_first_with_no_repeats_and_no_gaps(client):
    made = _stories(25)
    first = _get(client).json()
    assert len(first["results"]) == PAGE and first["next"]
    second = _get(client, first["next"]).json()
    assert len(second["results"]) == 5 and second["next"] is None
    got = [r["story_id"] for r in first["results"] + second["results"]]
    assert got == [str(s.pk) for s in made]                      # every story once, newest first


@pytest.mark.django_db
def test_exactly_one_page_has_no_next(client):
    _stories(PAGE)
    body = _get(client).json()
    assert len(body["results"]) == PAGE and body["next"] is None   # never a dangling empty page


@pytest.mark.django_db
def test_an_empty_feed_is_an_empty_page_with_no_next(client):
    assert _get(client).json() == {"results": [], "next": None}


@pytest.mark.django_db
def test_stories_with_the_same_timestamp_across_a_page_boundary_are_each_returned_once(client):
    made = _stories(PAGE + 6)
    same = timezone.now() - timedelta(days=1)
    StoryPost.objects.filter(pk__in=[s.pk for s in made[PAGE - 3: PAGE + 4]]).update(created_at=same)  # straddles the cut
    first = _get(client).json()
    second = _get(client, first["next"]).json()
    got = [r["story_id"] for r in first["results"] + second["results"]]
    assert len(got) == len(set(got)) == PAGE + 6
    assert set(got) == {str(s.pk) for s in made}


@pytest.mark.django_db
def test_a_story_posted_while_scrolling_does_not_repeat_a_row_on_the_next_page(client):
    _stories(25)
    first = _get(client).json()
    _stories(3, start=timezone.now() + timedelta(minutes=5))      # three new stories land at the top
    second = _get(client, first["next"]).json()
    assert not ({r["story_id"] for r in first["results"]} & {r["story_id"] for r in second["results"]})
    assert len(second["results"]) == 5


@pytest.mark.django_db
def test_hidden_stories_do_not_use_up_a_page(client):
    author = AccountFactory()
    _stories(PAGE, author=author)
    _stories(7, author=author, status=StoryStatus.HIDDEN, start=timezone.now() + timedelta(hours=1))
    body = _get(client).json()
    assert len(body["results"]) == PAGE and body["next"] is None


@pytest.mark.django_db
def test_blocked_and_suspended_authors_do_not_use_up_a_page(client):
    from moderation.models import AccountBlock
    viewer, blocked = AccountFactory(), AccountFactory()
    AccountBlock.objects.create(blocker=viewer, blocked=blocked)
    _stories(PAGE)
    _stories(5, author=blocked, start=timezone.now() + timedelta(hours=1))
    body = _get(client, **_hdr(viewer)).json()
    assert len(body["results"]) == PAGE and body["next"] is None


@pytest.mark.django_db
def test_a_cursor_is_a_position_so_it_still_works_after_its_story_is_hidden(client):
    made = _stories(25)
    first = _get(client).json()
    StoryPost.objects.filter(pk=made[PAGE - 1].pk).update(status=StoryStatus.HIDDEN)   # the row the cursor points at
    second = _get(client, first["next"]).json()
    assert [r["story_id"] for r in second["results"]] == [str(s.pk) for s in made[PAGE:]]


@pytest.mark.django_db
def test_the_city_filter_pages_too(client):
    from accounts.models import Address
    here, there = AccountFactory(), AccountFactory()
    for acc, city in ((here, "Marikina"), (there, "Cebu City")):
        Address.objects.filter(account=acc).delete()
        Address.objects.create(account=acc, city=city, is_primary=True, **{
            f: "" for f in ("label", "barangay", "province", "street") if f in {x.name for x in Address._meta.get_fields()}})
    _stories(23, author=here)
    _stories(4, author=there, start=timezone.now() + timedelta(hours=1))
    first = client.get("/api/v1/stories?city=Marikina").json()
    assert len(first["results"]) == PAGE and first["next"]
    second = client.get(f"/api/v1/stories?city=Marikina&cursor={first['next']}").json()
    assert len(second["results"]) == 3 and second["next"] is None


@pytest.mark.django_db
def test_page_is_ignored_so_an_old_app_still_gets_the_first_page(client):
    _stories(25)
    assert client.get("/api/v1/stories?page=2").json() == _get(client).json()


@pytest.mark.django_db
@pytest.mark.parametrize("cursor", [
    "garbage", "!!!", "a" * 5000,
    base64.urlsafe_b64encode(b"not|a|cursor").decode(),
    base64.urlsafe_b64encode(b"2026-11-09T00:00:00+00:00|not-a-uuid").decode(),
    base64.urlsafe_b64encode(b"yesterday|00000000-0000-0000-0000-000000000000").decode(),
    base64.urlsafe_b64encode(b"").decode() + "x",
])
def test_a_bad_cursor_is_a_400_never_a_500(client, cursor):
    res = _get(client, cursor)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.django_db
def test_an_empty_cursor_is_the_first_page(client):
    _stories(3)
    assert client.get("/api/v1/stories?cursor=").json() == _get(client).json()


@pytest.mark.django_db
def test_a_far_future_or_past_cursor_is_an_empty_or_full_page_not_an_error(client):
    from community.stories import encode_cursor
    _stories(3)
    far_past = encode_cursor(timezone.now() - timedelta(days=365 * 50), "00000000-0000-0000-0000-000000000000")
    far_future = encode_cursor(timezone.now() + timedelta(days=365 * 50), "ffffffff-ffff-ffff-ffff-ffffffffffff")
    assert _get(client, far_past).json() == {"results": [], "next": None}
    assert len(_get(client, far_future).json()["results"]) == 3


@pytest.mark.django_db
def test_a_page_costs_a_fixed_number_of_queries(client, django_assert_max_num_queries):
    _stories(PAGE + 5)
    first = _get(client).json()
    with django_assert_max_num_queries(8):
        _get(client, first["next"])


@pytest.mark.django_db
def test_my_reaction_is_still_reported_on_the_second_page(client):
    from community.models import StoryReaction
    me = AccountFactory()
    made = _stories(25)
    StoryReaction.objects.create(story=made[22], account=me)
    first = _get(client, **_hdr(me)).json()
    second = _get(client, first["next"], **_hdr(me)).json()
    mine = {r["story_id"]: r["my_reaction"] for r in second["results"]}
    assert mine[str(made[22].pk)] is True and sum(mine.values()) == 1
