"""Stories review (library docs/superpowers/specs/2026-11-09-stories-review.md), Critical steps 1-3.

Step 1 (ST1, ST15) · a story and its photos are written together or not at all, by one writer
(`community/stories.py`), and `story_posted` is emitted only once they have committed.
Step 2 (ST2, SQ2) · every photo is THIS account's own `story_photo` upload; erasing an account
removes its stories and their files.
Step 3 (ST3, ST4, SQ3) · a link is resolved and earned (the author is a party to an adoption that
happened or a rescue that resolved); the type comes from the link; one story per author per link.
"""
import json
import logging
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from community.models import StoryPhoto, StoryPost, StoryType
from listings.models import AdoptionListing, ListingStatus
from sagip.models import RescueCase, StrayReport


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def own(acc, name="a.jpg"):
    """A URL the presign endpoint would have handed this account for a story photo."""
    return f"https://bkt.example/story_photo/{acc.pk}/{name}"


def _post(client, acc, **body):
    body.setdefault("photos", [{"file_url": own(acc)}])
    return client.post("/api/v1/stories", body, content_type="application/json", **_hdr(acc))


def _events(caplog, name):
    return [json.loads(r.getMessage()) for r in caplog.records
            if r.name == "kupkop.analytics" and json.loads(r.getMessage())["event"] == name]


def _adopted_listing(poster, adopter=None, status=ListingStatus.ADOPTED):
    return AdoptionListing.objects.create(posted_by=poster, adopted_by_account=adopter, name="Bantay",
                                          species="dog", city="Marikina", adoption_fee="0", status=status)


def _case(claimer, reporter=None, resolved=True):
    report = StrayReport.objects.create(species="dog", condition="injured",
                                        geom=Point(121.0, 14.6, srid=4326), reporter_account=reporter)
    return RescueCase.objects.create(report=report, claimed_by_account=claimer,
                                     resolved_at=timezone.now() if resolved else None)


# ── Step 1 · atomic, one writer ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_a_failed_photo_insert_writes_no_story_and_emits_nothing(client, caplog):
    acc = AccountFactory()
    real = StoryPhoto.objects.create
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("connection dropped")
        return real(**kw)

    client.raise_request_exception = False
    with caplog.at_level(logging.INFO, logger="kupkop.analytics"), \
            mock.patch.object(StoryPhoto.objects, "create", side_effect=flaky):
        res = _post(client, acc, photos=[{"file_url": own(acc, "a.jpg")}, {"file_url": own(acc, "b.jpg")}])
    assert res.status_code == 500
    assert not StoryPost.objects.filter(author_account=acc).exists()
    assert not StoryPhoto.objects.exists()
    assert _events(caplog, "story_posted") == []


@pytest.mark.django_db
def test_story_posted_waits_for_the_commit(client, caplog, django_capture_on_commit_callbacks):
    acc = AccountFactory()
    with caplog.at_level(logging.INFO, logger="kupkop.analytics"):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            res = _post(client, acc)
        assert res.status_code == 201
        assert _events(caplog, "story_posted") == []          # nothing yet: not committed
        for cb in callbacks:
            cb()
    posted = _events(caplog, "story_posted")
    assert len(posted) == 1 and posted[0]["story_type"] == "general"


@pytest.mark.django_db
def test_the_writer_is_callable_without_a_request():
    from community.stories import create_story
    acc = AccountFactory()
    story = create_story(acc, caption="Hi", photos=[{"file_url": own(acc), "is_primary": True}])
    assert story.story_type == StoryType.GENERAL
    assert list(story.photos.values_list("url", "is_primary")) == [(own(acc), True)]


# ── Step 2 · own uploads only ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "http://tracker.example/p.gif",
    "https://bkt.example/story_photo/{other}/a.jpg",     # another account's upload
    "https://bkt.example/listing_photo/{me}/a.jpg",      # my upload, for another purpose
    "https://bkt.example/story_photo/{me}/a.jpg?sig=1",  # a query string
    "",
    "https://bkt.example/story_photo/{me}/" + "a" * 600,
])
def test_a_photo_that_is_not_my_story_upload_is_refused(client, url):
    me, other = AccountFactory(), AccountFactory()
    res = _post(client, me, photos=[{"file_url": url.format(me=me.pk, other=other.pk)}])
    assert res.status_code == 400
    assert res.json()["error"]["field"] == "photos"
    assert not StoryPost.objects.filter(author_account=me).exists()


@pytest.mark.django_db
def test_one_bad_photo_among_good_ones_refuses_the_whole_story(client):
    me = AccountFactory()
    res = _post(client, me, photos=[{"file_url": own(me)}, {"file_url": "https://evil.example/x.jpg"}])
    assert res.status_code == 400
    assert not StoryPost.objects.exists()


@pytest.mark.django_db
def test_my_own_story_upload_is_accepted(client):
    me = AccountFactory()
    assert _post(client, me).status_code == 201


@pytest.mark.django_db
def test_erasing_an_account_removes_its_stories_and_their_own_files():
    from accounts.lifecycle import soft_delete_account
    from accounts.purge import anonymize_expired_accounts
    gone, reader = AccountFactory(), AccountFactory()
    story = StoryPost.objects.create(author_account=gone, story_type="general", caption="Our dog")
    StoryPhoto.objects.create(story=story, url=own(gone), is_primary=True)
    StoryPhoto.objects.create(story=story, url="https://bkt.example/story_photo/someone-else/x.jpg")  # legacy row
    others = StoryPost.objects.create(author_account=reader, story_type="general")
    soft_delete_account(gone)
    gone.deleted_at = timezone.now() - timedelta(days=31)
    gone.save(update_fields=["deleted_at"])

    with mock.patch("accounts.purge.delete_object") as delete_object:
        anonymize_expired_accounts()

    assert not StoryPost.objects.filter(pk=story.pk).exists()
    assert not StoryPhoto.objects.filter(story_id=story.pk).exists()
    deleted = {c.args[0] for c in delete_object.call_args_list}
    assert own(gone) in deleted
    assert "https://bkt.example/story_photo/someone-else/x.jpg" not in deleted   # never a stranger's file
    assert StoryPost.objects.filter(pk=others.pk).exists()


# ── Step 3 · links are checked and earned ───────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("field", ["adoption_listing_id", "rescue_case_id"])
def test_an_unknown_link_is_a_422_not_a_500(client, field, caplog):
    acc = AccountFactory()
    with caplog.at_level(logging.INFO, logger="kupkop.analytics"):
        res = _post(client, acc, **{field: str(uuid.uuid4())})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "link_not_found"
    assert not StoryPost.objects.exists()
    assert _events(caplog, "story_posted") == []


@pytest.mark.django_db
def test_a_stranger_cannot_link_someone_elses_adoption(client):
    listing = _adopted_listing(AccountFactory(), adopter=AccountFactory())
    res = _post(client, AccountFactory(), adoption_listing_id=str(listing.pk))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "not_your_story"


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["poster", "adopter"])
def test_the_poster_and_the_adopter_may_link_an_adopted_listing(client, who):
    poster, adopter = AccountFactory(), AccountFactory()
    listing = _adopted_listing(poster, adopter=adopter)
    res = _post(client, {"poster": poster, "adopter": adopter}[who], adoption_listing_id=str(listing.pk))
    assert res.status_code == 201
    story = StoryPost.objects.get(pk=res.json()["story_id"])
    assert story.story_type == StoryType.ADOPTION and story.adoption_listing_id == listing.pk


@pytest.mark.django_db
@pytest.mark.parametrize("status", [ListingStatus.AVAILABLE, ListingStatus.PENDING, ListingStatus.DRAFT,
                                    ListingStatus.WITHDRAWN])
def test_a_listing_that_was_not_adopted_cannot_be_linked(client, status):
    poster = AccountFactory()
    listing = _adopted_listing(poster, status=status)
    res = _post(client, poster, adoption_listing_id=str(listing.pk))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "link_not_eligible"


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["claimer", "reporter"])
def test_the_claimer_and_the_reporter_may_link_a_resolved_rescue(client, who):
    claimer, reporter = AccountFactory(), AccountFactory()
    case = _case(claimer, reporter)
    res = _post(client, {"claimer": claimer, "reporter": reporter}[who], rescue_case_id=str(case.pk),
                story_type="general")
    assert res.status_code == 201
    assert StoryPost.objects.get(pk=res.json()["story_id"]).story_type == StoryType.RESCUE   # the link wins


@pytest.mark.django_db
def test_a_stranger_cannot_link_a_rescue(client):
    case = _case(AccountFactory(), AccountFactory())
    res = _post(client, AccountFactory(), rescue_case_id=str(case.pk))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "not_your_story"


@pytest.mark.django_db
def test_a_rescue_still_in_progress_cannot_be_linked(client):
    claimer = AccountFactory()
    res = _post(client, claimer, rescue_case_id=str(_case(claimer, resolved=False).pk))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "link_not_eligible"


@pytest.mark.django_db
def test_both_links_at_once_is_refused(client):
    poster = AccountFactory()
    res = _post(client, poster, adoption_listing_id=str(_adopted_listing(poster).pk),
                rescue_case_id=str(_case(poster).pk))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "one_link_only"


@pytest.mark.django_db
@pytest.mark.parametrize("claimed", ["adoption", "rescue"])
def test_an_adoption_or_rescue_type_needs_its_link(client, claimed):
    res = _post(client, AccountFactory(), story_type=claimed)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "link_required"


@pytest.mark.django_db
def test_no_link_and_no_type_is_a_general_story(client):
    res = _post(client, AccountFactory())
    assert StoryPost.objects.get(pk=res.json()["story_id"]).story_type == StoryType.GENERAL


@pytest.mark.django_db
def test_a_null_link_is_the_same_as_no_link(client):
    res = _post(client, AccountFactory(), adoption_listing_id=None, rescue_case_id=None)
    assert res.status_code == 201


@pytest.mark.django_db
def test_one_story_per_author_per_adoption(client):
    poster = AccountFactory()
    listing = _adopted_listing(poster)
    assert _post(client, poster, adoption_listing_id=str(listing.pk)).status_code == 201
    res = _post(client, poster, adoption_listing_id=str(listing.pk), photos=[{"file_url": own(poster, "b.jpg")}])
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "story_exists"
    assert StoryPost.objects.filter(adoption_listing=listing).count() == 1


@pytest.mark.django_db
def test_the_adopter_and_the_poster_each_get_their_own_story_on_one_adoption(client):
    poster, adopter = AccountFactory(), AccountFactory()
    listing = _adopted_listing(poster, adopter=adopter)
    assert _post(client, poster, adoption_listing_id=str(listing.pk)).status_code == 201
    assert _post(client, adopter, adoption_listing_id=str(listing.pk)).status_code == 201


@pytest.mark.django_db
def test_one_story_per_author_per_rescue(client):
    claimer = AccountFactory()
    case = _case(claimer)
    assert _post(client, claimer, rescue_case_id=str(case.pk)).status_code == 201
    assert _post(client, claimer, rescue_case_id=str(case.pk)).status_code == 409


@pytest.mark.django_db
def test_the_database_holds_one_per_link_when_the_check_is_raced():
    """The writer checks first; the constraint is what holds two racing posts to one row."""
    from django.db import IntegrityError, transaction
    poster = AccountFactory()
    listing = _adopted_listing(poster)
    StoryPost.objects.create(author_account=poster, adoption_listing=listing, story_type="adoption")
    with pytest.raises(IntegrityError), transaction.atomic():
        StoryPost.objects.create(author_account=poster, adoption_listing=listing, story_type="adoption")
