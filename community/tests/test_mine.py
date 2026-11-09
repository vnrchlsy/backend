"""Moderation walk W1 · the app offered an author "Report this person", "Block" and "Report this" on their OWN story, and a poster the same on
their own listing. The server refuses them (own_content / own_account), so nothing broke, but the controls should not be there. The detail now
says whether it is the viewer's own, and the app hides the controls when it is."""
import pytest

from accounts.factories import AccountFactory
from community.models import StoryPost
from listings.tests.adoption_helpers import c, listing, person


def _story(author, **kw):
    return StoryPost.objects.create(author_account=author, story_type="general", caption="x", **kw)


@pytest.mark.django_db
def test_an_author_is_told_a_story_is_theirs_and_nobody_else_is():
    author, other = person(), person()
    story = _story(author)
    assert c(author).get(f"/api/v1/stories/{story.pk}").json()["mine"] is True
    assert c(other).get(f"/api/v1/stories/{story.pk}").json()["mine"] is False


@pytest.mark.django_db
def test_a_guest_is_never_the_author(client):
    story = _story(person())
    assert client.get(f"/api/v1/stories/{story.pk}").json()["mine"] is False


@pytest.mark.django_db
def test_a_hidden_story_is_still_marked_as_the_authors_own():
    author = person()
    story = _story(author, status="hidden")
    body = c(author).get(f"/api/v1/stories/{story.pk}").json()
    assert body["status"] == "hidden" and body["mine"] is True


@pytest.mark.django_db
def test_a_poster_is_told_a_listing_is_theirs_and_nobody_else_is(client):
    poster, other = person(), person()
    live = listing(poster)
    assert c(poster).get(f"/api/v1/listings/{live.pk}").json()["mine"] is True
    assert c(other).get(f"/api/v1/listings/{live.pk}").json()["mine"] is False
    assert client.get(f"/api/v1/listings/{live.pk}").json()["mine"] is False


@pytest.mark.django_db
def test_the_flag_is_about_the_viewer_not_the_content_so_an_unrelated_account_never_sees_true():
    a, b = AccountFactory(), AccountFactory()
    story = _story(a)
    assert c(b).get(f"/api/v1/stories/{story.pk}").json()["mine"] is False
