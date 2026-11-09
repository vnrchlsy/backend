"""Stories review step 5 (ST6, ST16) · a story has one declared shape, a date, and a link the viewer may open.

`_story_repr` built the answer by hand and the app read it as `any`, in three hand-copied types. Now `StorySerializer` says what a story is, the feed and the
detail are checked against it, and a test reads the app's TypeScript types and compares their keys with it (as for /me/impact, IB26). The row also carries what
was stored and never shown: `created_at` (UTC, with a Z) and `link`, the adoption or rescue the story is about, only when the viewer could open it, through the
screens that already gate it (D-S6-4).
"""
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from common.tests import mobile_types
from community.models import StoryPhoto, StoryPost, StoryReaction
from community.serializers import (
    StoryAuthorSerializer,
    StoryLinkSerializer,
    StoryPageSerializer,
    StoryPhotoOutSerializer,
    StorySerializer,
)
from listings.models import AdoptionListing, ListingStatus
from sagip.models import RescueCase, StrayReport
from verifications.models import AccountCapability


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def _verified(acc):
    """A Verified Member: the poster a public listing needs (listings/visibility.public_poster_q)."""
    AccountCapability.objects.create(account=acc, capability="rescuer", status="approved")
    return acc


def _listing(poster=None, **kw):
    poster = poster or _verified(AccountFactory())
    return AdoptionListing.objects.create(posted_by=poster, name="Bantay", species="dog", city="Marikina", adoption_fee="0",
                                          status=kw.pop("status", ListingStatus.ADOPTED), **kw)


def _case(claimer=None, reporter=None, hidden=False):
    report = StrayReport.objects.create(species="dog", condition="injured", geom=Point(121.0, 14.6, srid=4326),
                                        reporter_account=reporter, hidden_at=timezone.now() if hidden else None)
    return RescueCase.objects.create(report=report, claimed_by_account=claimer or AccountFactory(), resolved_at=timezone.now())


def _story(author=None, photos=(("https://x/0.jpg", True),), **kw):
    s = StoryPost.objects.create(author_account=author or AccountFactory(), story_type=kw.pop("story_type", "general"), caption="Home", **kw)
    for url, primary in photos:
        StoryPhoto.objects.create(story=s, url=url, is_primary=primary)
    return s


def _feed(client, viewer=None):
    return client.get("/api/v1/stories", **(_hdr(viewer) if viewer else {})).json()["results"]


def _row(client, story, viewer=None):
    return next(r for r in _feed(client, viewer) if r["story_id"] == str(story.pk))


# ── the response is its serializer ──────────────────────────────
@pytest.mark.django_db
def test_the_feed_and_the_page_are_valid_against_their_contract(client):
    _story()
    body = client.get("/api/v1/stories").json()
    page = StoryPageSerializer(data=body)
    assert page.is_valid(), page.errors
    assert set(body) == set(StoryPageSerializer().fields)


@pytest.mark.django_db
def test_every_feed_row_has_exactly_the_contracts_keys(client):
    _story()
    for row in _feed(client):
        assert set(row) == set(StorySerializer().fields)


@pytest.mark.django_db
def test_the_detail_is_the_same_shape_as_a_feed_row(client):
    s = _story()
    body = client.get(f"/api/v1/stories/{s.pk}").json()
    assert set(body) == set(StorySerializer().fields)
    assert StorySerializer(data=body).is_valid()
    assert body == _row(client, s)


@pytest.mark.django_db
def test_an_empty_feed_is_a_valid_page(client):
    assert StoryPageSerializer(data=client.get("/api/v1/stories").json()).is_valid()


# ── the date ────────────────────────────────────────────────────
@pytest.mark.django_db
def test_created_at_is_the_posting_time_in_utc_with_a_z(client):
    when = timezone.now() - timedelta(days=3)
    s = _story()
    StoryPost.objects.filter(pk=s.pk).update(created_at=when)
    row = _row(client, s)
    assert row["created_at"].endswith("Z") and "+" not in row["created_at"]
    assert row["created_at"].startswith(when.strftime("%Y-%m-%dT%H:%M:%S"))


# ── photos ──────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_primary_photo_comes_first_and_is_named(client):
    s = _story(photos=(("https://x/a.jpg", False), ("https://x/b.jpg", True), ("https://x/c.jpg", False)))
    row = _row(client, s)
    assert row["primary_photo"] == "https://x/b.jpg"
    assert row["photos"][0] == {"url": "https://x/b.jpg", "is_primary": True}
    assert {p["url"] for p in row["photos"]} == {"https://x/a.jpg", "https://x/b.jpg", "https://x/c.jpg"}


@pytest.mark.django_db
def test_with_no_primary_marked_the_first_photo_leads(client):
    s = _story(photos=(("https://x/a.jpg", False), ("https://x/b.jpg", False)))
    row = _row(client, s)
    assert row["primary_photo"] == row["photos"][0]["url"]


@pytest.mark.django_db
def test_a_story_with_no_photos_still_serializes(client):
    s = _story(photos=())                       # a data repair case; compose requires one
    row = _row(client, s)
    assert row["photos"] == [] and row["primary_photo"] is None
    assert StorySerializer(data=row).is_valid()


@pytest.mark.django_db
def test_the_photo_order_is_the_same_on_every_read(client):
    s = _story(photos=tuple((f"https://x/{i}.jpg", False) for i in range(6)))
    assert len({tuple(p["url"] for p in _row(client, s)["photos"]) for _ in range(4)}) == 1


# ── mine ────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_mine_is_true_only_for_the_authors_own_story_in_the_feed_and_the_detail(client):
    me, other = AccountFactory(), AccountFactory()
    mine, theirs = _story(author=me), _story(author=other)
    assert _row(client, mine, me)["mine"] is True and _row(client, theirs, me)["mine"] is False
    assert _row(client, mine)["mine"] is False                                  # a guest owns nothing
    assert client.get(f"/api/v1/stories/{mine.pk}", **_hdr(me)).json()["mine"] is True
    assert client.get(f"/api/v1/stories/{theirs.pk}", **_hdr(me)).json()["mine"] is False


@pytest.mark.django_db
def test_my_reaction_and_the_count_are_in_the_row(client):
    me, s = AccountFactory(), _story()
    StoryReaction.objects.create(story=s, account=me)
    StoryReaction.objects.create(story=s, account=AccountFactory())
    row = _row(client, s, me)
    assert row["my_reaction"] is True and row["reaction_count"] == 2


# ── the link ────────────────────────────────────────────────────
@pytest.mark.django_db
def test_an_adoption_story_links_to_its_public_listing(client):
    listing = _listing()
    s = _story(story_type="adoption", adoption_listing=listing)
    assert _row(client, s)["link"] == {"type": "adoption", "id": str(listing.pk)}


@pytest.mark.django_db
def test_a_rescue_story_links_to_its_public_report_by_the_reports_id(client):
    case = _case()
    s = _story(story_type="rescue", rescue_case=case)
    assert _row(client, s)["link"] == {"type": "rescue", "id": str(case.report_id)}      # the id the report screen opens


@pytest.mark.django_db
def test_a_story_about_nothing_has_no_link(client):
    assert _row(client, _story())["link"] is None


@pytest.mark.django_db
def test_no_link_when_its_listing_was_taken_down(client):
    listing = _listing(hidden_at=timezone.now())
    assert _row(client, _story(story_type="adoption", adoption_listing=listing))["link"] is None


@pytest.mark.django_db
def test_no_link_when_the_poster_is_not_publicly_visible(client):
    unverified = AccountFactory()                        # not a Verified Member: the listing is not public by link
    assert _row(client, _story(story_type="adoption", adoption_listing=_listing(poster=unverified)))["link"] is None


@pytest.mark.django_db
def test_the_poster_can_still_open_their_own_listing_from_the_story(client):
    unverified = AccountFactory()
    listing = _listing(poster=unverified)
    s = _story(author=unverified, story_type="adoption", adoption_listing=listing)
    assert _row(client, s, unverified)["link"] == {"type": "adoption", "id": str(listing.pk)}


@pytest.mark.django_db
def test_no_link_to_a_listing_whose_poster_the_viewer_blocked(client):
    from moderation.models import AccountBlock
    viewer, poster = AccountFactory(), _verified(AccountFactory())
    AccountBlock.objects.create(blocker=viewer, blocked=poster)
    s = _story(story_type="adoption", adoption_listing=_listing(poster=poster))
    assert _row(client, s, viewer)["link"] is None


@pytest.mark.django_db
def test_no_link_when_the_report_was_taken_down_except_to_the_people_in_it(client):
    reporter, claimer, stranger = AccountFactory(), AccountFactory(), AccountFactory()
    case = _case(claimer=claimer, reporter=reporter, hidden=True)
    s = _story(author=claimer, story_type="rescue", rescue_case=case)
    assert _row(client, s)["link"] is None
    assert _row(client, s, stranger)["link"] is None
    assert _row(client, s, claimer)["link"] == {"type": "rescue", "id": str(case.report_id)}
    assert _row(client, s, reporter)["link"] == {"type": "rescue", "id": str(case.report_id)}


@pytest.mark.django_db
def test_a_link_whose_target_was_deleted_is_just_no_link(client):
    listing = _listing()
    s = _story(story_type="adoption", adoption_listing=listing)
    AdoptionListing.objects.filter(pk=listing.pk).delete()                      # the FK is SET NULL
    assert _row(client, s)["link"] is None
    assert StorySerializer(data=_row(client, s)).is_valid()


@pytest.mark.django_db
def test_the_detail_carries_the_same_link_as_the_feed(client):
    listing = _listing()
    s = _story(story_type="adoption", adoption_listing=listing)
    assert client.get(f"/api/v1/stories/{s.pk}").json()["link"] == {"type": "adoption", "id": str(listing.pk)}


@pytest.mark.django_db
def test_a_page_of_linked_stories_costs_a_fixed_number_of_queries(client, django_assert_max_num_queries):
    poster = _verified(AccountFactory())
    for _ in range(10):
        _story(story_type="adoption", adoption_listing=_listing(poster=poster))
    for _ in range(10):
        _story(story_type="rescue", rescue_case=_case())
    with django_assert_max_num_queries(12):
        rows = _feed(client)
    assert sum(1 for r in rows if r["link"]) == 20


# ── the contract refuses a bad shape ────────────────────────────
@pytest.mark.parametrize("bad", [
    {},
    {"next": None},
    {"results": "x", "next": None},
    {"results": [{"story_id": "x"}], "next": None},
    {"results": [], "next": {}},
])
def test_the_contract_rejects_a_payload_that_is_not_the_shape(bad):
    assert not StoryPageSerializer(data=bad).is_valid()


def test_a_link_needs_a_known_type():
    assert not StoryLinkSerializer(data={"type": "wishlist", "id": "00000000-0000-0000-0000-000000000000"}).is_valid()


# ── the app's types are held to it (skips without mobile_app/) ──
needs_mobile = pytest.mark.skipif(not mobile_types.available("community.ts"),
                                  reason="mobile_app not checked out beside backend/ (set KUPKOP_MOBILE_APP)")
TYPE_FILES = ("community.ts", "screens/StoriesScreen.tsx", "screens/StoryDetailScreen.tsx")


@needs_mobile
def test_the_apps_story_is_the_servers():
    assert mobile_types.ts_keys("Story", *TYPE_FILES) == set(StorySerializer().fields)


@needs_mobile
def test_the_apps_story_page_is_the_servers():
    assert mobile_types.ts_keys("StoryPage", *TYPE_FILES) == set(StoryPageSerializer().fields)


@needs_mobile
def test_the_apps_story_link_author_and_photo_are_the_servers():
    assert mobile_types.ts_keys("StoryLink", *TYPE_FILES) == set(StoryLinkSerializer().fields)
    assert mobile_types.ts_keys("StoryAuthor", *TYPE_FILES) == set(StoryAuthorSerializer().fields)
    assert mobile_types.ts_keys("StoryPhoto", *TYPE_FILES) == set(StoryPhotoOutSerializer().fields)
