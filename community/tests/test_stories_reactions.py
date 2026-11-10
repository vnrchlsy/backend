"""Stories review step 9 (ST9, ST10) · reacting answers with the state, and un-reacting obeys the same visibility as reacting.

Before, `DELETE /stories/{id}/reactions` checked only that the row existed: on a hidden story, a blocked author's, a suspended author's or one the author deleted it answered
200 with the reaction count, so the count of a story nobody may see could be read, and 200 against 404 showed that it existed. And both answers carried `reaction_count`
only, so the app guessed `my_reaction` from what it had just sent.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from accounts.factories import AccountFactory
from accounts.models import AccountStatus
from accounts.tokens import tokens_for
from community.models import StoryPhoto, StoryPost, StoryReaction, StoryStatus
from moderation.models import AccountBlock

URL = "/api/v1/stories"


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _story(author=None, status=StoryStatus.PUBLISHED):
    s = StoryPost.objects.create(author_account=author or AccountFactory(), story_type="general", status=status)
    StoryPhoto.objects.create(story=s, url="https://x/a.jpg", is_primary=True)
    return s


def _react(client, story, acc=None):
    return client.post(f"{URL}/{story.pk}/reactions", **(_hdr(acc) if acc else {}))


def _unreact(client, story, acc=None):
    return client.delete(f"{URL}/{story.pk}/reactions", **(_hdr(acc) if acc else {}))


# ── both answers carry the state ────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_reacting_answers_with_the_count_and_that_it_is_on(client):
    me, s = AccountFactory(), _story()
    StoryReaction.objects.create(story=s, account=AccountFactory())
    res = _react(client, s, me)
    assert res.status_code == 200 and res.json() == {"reaction_count": 2, "my_reaction": True}


@pytest.mark.django_db
def test_un_reacting_answers_with_the_count_and_that_it_is_off(client):
    me, s = AccountFactory(), _story()
    StoryReaction.objects.create(story=s, account=me)
    StoryReaction.objects.create(story=s, account=AccountFactory())
    res = _unreact(client, s, me)
    assert res.status_code == 200 and res.json() == {"reaction_count": 1, "my_reaction": False}


@pytest.mark.django_db
def test_reacting_twice_is_still_one_row_and_both_answers_say_on(client):
    me, s = AccountFactory(), _story()
    first, second = _react(client, s, me), _react(client, s, me)
    assert first.json() == second.json() == {"reaction_count": 1, "my_reaction": True}
    assert StoryReaction.objects.filter(story=s).count() == 1


@pytest.mark.django_db
def test_un_reacting_twice_or_without_ever_reacting_is_200_and_off(client):
    me, s = AccountFactory(), _story()
    StoryReaction.objects.create(story=s, account=AccountFactory())
    assert _unreact(client, s, me).json() == {"reaction_count": 1, "my_reaction": False}     # never reacted: nothing to remove
    _react(client, s, me)
    assert _unreact(client, s, me).json()["my_reaction"] is False
    assert _unreact(client, s, me).json() == {"reaction_count": 1, "my_reaction": False}     # again: the same


@pytest.mark.django_db
def test_my_unreacting_removes_only_mine(client):
    me, other, s = AccountFactory(), AccountFactory(), _story()
    StoryReaction.objects.create(story=s, account=me)
    StoryReaction.objects.create(story=s, account=other)
    _unreact(client, s, me)
    assert list(StoryReaction.objects.filter(story=s).values_list("account_id", flat=True)) == [other.pk]


@pytest.mark.django_db
def test_a_guest_can_do_neither(client):
    s = _story()
    assert _react(client, s).status_code == 401 and _unreact(client, s).status_code == 401


@pytest.mark.django_db
def test_the_answer_agrees_with_the_feed_and_the_detail(client):
    me, s = AccountFactory(), _story()
    answer = _react(client, s, me).json()
    detail = client.get(f"{URL}/{s.pk}", **_hdr(me)).json()
    assert (answer["reaction_count"], answer["my_reaction"]) == (detail["reaction_count"], detail["my_reaction"])
    row = next(r for r in client.get(URL, **_hdr(me)).json()["results"] if r["story_id"] == str(s.pk))
    assert (row["reaction_count"], row["my_reaction"]) == (answer["reaction_count"], answer["my_reaction"])


# ── un-reacting obeys the same visibility as reacting ───────────────────────────────────────────
def _hidden(me):
    return _story(status=StoryStatus.HIDDEN)


def _removed(me):
    return _story(status=StoryStatus.REMOVED)


def _suspended_author(me):
    return _story(author=AccountFactory(status=AccountStatus.SUSPENDED))


def _blocked_by_me(me):
    author = AccountFactory()
    AccountBlock.objects.create(blocker=me, blocked=author)
    return _story(author=author)


def _blocked_me(me):
    author = AccountFactory()
    AccountBlock.objects.create(blocker=author, blocked=me)
    return _story(author=author)


@pytest.mark.django_db
@pytest.mark.parametrize("make", [_hidden, _removed, _suspended_author, _blocked_by_me, _blocked_me], ids=lambda f: f.__name__.strip("_"))
def test_neither_reacting_nor_un_reacting_works_on_a_story_the_viewer_may_not_see(client, make):
    me = AccountFactory()
    s = make(me)
    StoryReaction.objects.create(story=s, account=AccountFactory())                       # someone else's reaction: must not be readable
    assert _react(client, s, me).status_code == 404
    res = _unreact(client, s, me)
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
    assert "reaction_count" not in res.json()                                              # the count of a story nobody may see is not leaked


@pytest.mark.django_db
def test_an_unknown_story_is_404_for_both(client):
    me = AccountFactory()
    missing = type("S", (), {"pk": "00000000-0000-0000-0000-000000000000"})()
    assert _react(client, missing, me).status_code == 404 and _unreact(client, missing, me).status_code == 404


@pytest.mark.django_db
def test_an_un_react_on_a_story_that_went_hidden_leaves_the_row_alone(client):
    me, s = AccountFactory(), _story()
    _react(client, s, me)
    StoryPost.objects.filter(pk=s.pk).update(status=StoryStatus.HIDDEN)
    assert _unreact(client, s, me).status_code == 404
    assert StoryReaction.objects.filter(story=s, account=me).exists()                      # restored later, the reaction is still there


@pytest.mark.django_db
def test_the_author_may_react_to_their_own_story_and_take_it_back(client):
    me = AccountFactory()
    s = _story(author=me)
    assert _react(client, s, me).json() == {"reaction_count": 1, "my_reaction": True}
    assert _unreact(client, s, me).json() == {"reaction_count": 0, "my_reaction": False}


# ── a racing double tap ─────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_a_burst_of_reacts_from_one_person_is_one_row_and_never_a_500():
    from django.test import Client
    me, s = AccountFactory(), _story()

    def tap(_):
        try:
            return Client().post(f"{URL}/{s.pk}/reactions", **_hdr(me)).status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(tap, range(16)))
    assert set(codes) == {200}
    assert StoryReaction.objects.filter(story=s, account=me).count() == 1
