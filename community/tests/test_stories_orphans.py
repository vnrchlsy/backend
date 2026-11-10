"""Stories test plan F6 · an upload that succeeded and a post that never did leaves a file nobody cites. A nightly sweep removes it.

The rule (review F6): delete `story_photo/` keys older than 24 hours that no `story_photo` row cites. 24 hours is the grace for a person who uploaded,
walked away and posted later. Everything else is protection against the sweep deleting something it should not: only that prefix; a cited key is kept
whether its story is live, hidden or soft-deleted (the row is evidence for 30 days); a storage error never stops it; and if most of what it found looks
orphaned, it refuses to delete anything, because that shape means its idea of "cited" is wrong, not that the bucket is full of litter.
"""
import json
import logging
from datetime import timedelta
from unittest import mock

import boto3
import pytest
from django.utils import timezone
from moto import mock_aws

from accounts.factories import AccountFactory
from community.models import StoryPhoto, StoryPost, StoryStatus
from community.stories import ORPHAN_GRACE_HOURS, sweep_orphan_story_uploads

NOW = timezone.now()
BUCKET = "https://bkt.example"


def key(acc, name="a.jpg"):
    return f"story_photo/{acc.pk}/{name}"


def _cited(acc, name, status=StoryStatus.PUBLISHED):
    s = StoryPost.objects.create(author_account=acc, story_type="general", caption="x", status=status)
    StoryPhoto.objects.create(story=s, url=f"{BUCKET}/{key(acc, name)}", is_primary=True, position=0)
    return s


def _lister(objects):
    """What `list_objects` yields: (key, last_modified)."""
    def lister(visibility, prefix):
        assert prefix == "story_photo/"                                     # the sweep only ever asks about stories
        return iter(objects)
    return lister


class Bin:
    def __init__(self, fail=()):
        self.deleted, self.fail = [], set(fail)

    def __call__(self, file_url, visibility):
        if any(f in file_url for f in self.fail):
            raise RuntimeError("AccessDenied")
        self.deleted.append(file_url)


def _sweep(objects, bin_=None, now=None):
    bin_ = bin_ if bin_ is not None else Bin()
    n = sweep_orphan_story_uploads(now=now or NOW, lister=_lister(objects), deleter=bin_)
    return n, bin_


def _old(k):
    return (k, NOW - timedelta(hours=ORPHAN_GRACE_HOURS + 1))


# ---- the rule ----------------------------------------------------------------------------------------------------------------
@pytest.mark.django_db
def test_an_old_upload_nobody_cites_is_deleted_and_a_cited_one_is_kept():
    me = AccountFactory()
    _cited(me, "kept.jpg")
    n, bin_ = _sweep([_old(key(me, "kept.jpg")), _old(key(me, "orphan.jpg")), _old(key(me, "orphan2.jpg"))])
    # 2 of 3 look orphaned: below the valve's minimum count, so it runs (the valve has its own test).
    assert n == 2 and sorted(u.rsplit("/", 1)[-1] for u in bin_.deleted) == ["orphan.jpg", "orphan2.jpg"]


@pytest.mark.django_db
def test_a_recent_upload_is_left_alone_so_a_slow_post_still_works():
    me = AccountFactory()
    fresh = (key(me, "fresh.jpg"), NOW - timedelta(hours=ORPHAN_GRACE_HOURS - 1))
    n, bin_ = _sweep([fresh])
    assert n == 0 and bin_.deleted == []


@pytest.mark.django_db
def test_exactly_at_the_grace_is_not_yet_an_orphan():
    me = AccountFactory()
    n, bin_ = _sweep([(key(me, "edge.jpg"), NOW - timedelta(hours=ORPHAN_GRACE_HOURS))])
    assert n == 0 and bin_.deleted == []


@pytest.mark.django_db
@pytest.mark.parametrize("status", [StoryStatus.PUBLISHED, StoryStatus.HIDDEN, StoryStatus.REMOVED])
def test_a_cited_key_is_kept_whatever_state_its_story_is_in(status):
    me = AccountFactory()
    _cited(me, "x.jpg", status=status)                    # a soft-deleted story's files are kept for its 30 days
    n, bin_ = _sweep([_old(key(me, "x.jpg"))])
    assert n == 0 and bin_.deleted == []


@pytest.mark.django_db
def test_only_the_story_photo_prefix_is_ever_touched():
    me = AccountFactory()
    other = [_old(f"pet_photo/{me.pk}/a.jpg"), _old(f"avatar/{me.pk}/a.jpg"), _old("story_photos/x.jpg"), _old("story_photo")]
    n, bin_ = _sweep(other + [_old(key(me, "o.jpg"))])
    assert n == 1 and [u.rsplit("/", 1)[-1] for u in bin_.deleted] == ["o.jpg"]


@pytest.mark.django_db
def test_a_cited_url_in_another_host_form_still_counts_as_cited():
    # A row written when the bucket was reached by another host (a CDN, a region) names the same KEY. The match is on the key, not the whole URL.
    me = AccountFactory()
    s = StoryPost.objects.create(author_account=me, story_type="general", caption="x")
    StoryPhoto.objects.create(story=s, url=f"https://cdn.example.net/{key(me, 'cdn.jpg')}", is_primary=True, position=0)
    n, bin_ = _sweep([_old(key(me, "cdn.jpg"))])
    assert n == 0 and bin_.deleted == []


# ---- it never makes things worse ------------------------------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_storage_error_does_not_stop_the_sweep_and_is_logged_by_key(caplog):
    me = AccountFactory()
    objs = [_old(key(me, f"o{i}.jpg")) for i in range(12)] + [_old(key(me, f"c{i}.jpg")) for i in range(60)]
    for i in range(60):
        _cited(me, f"c{i}.jpg")
    with caplog.at_level(logging.WARNING, logger="kupkop.storage"):
        n, bin_ = _sweep(objs, Bin(fail=["o3.jpg"]))
    assert n == 11 and len(bin_.deleted) == 11
    assert any(key(me, "o3.jpg") in r.getMessage() for r in caplog.records)
    assert not any(str(me.email) in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_when_most_of_what_it_finds_looks_orphaned_it_deletes_nothing_and_says_so(caplog):
    # The failure this guards: the sweep's idea of "cited" is wrong (a URL form it does not know), so EVERYTHING looks orphaned.
    me = AccountFactory()
    objs = [_old(key(me, f"m{i}.jpg")) for i in range(200)]
    with caplog.at_level(logging.ERROR, logger="kupkop.storage"):
        n, bin_ = _sweep(objs)
    assert n == 0 and bin_.deleted == []
    assert any("refusing" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.django_db
def test_a_normal_night_under_the_valve_is_not_refused():
    me = AccountFactory()
    for i in range(100):
        _cited(me, f"c{i}.jpg")
    objs = [_old(key(me, f"c{i}.jpg")) for i in range(100)] + [_old(key(me, f"o{i}.jpg")) for i in range(5)]
    n, bin_ = _sweep(objs)
    assert n == 5 and len(bin_.deleted) == 5


@pytest.mark.django_db
def test_it_is_idempotent_and_takes_an_explicit_clock():
    me = AccountFactory()
    for i in range(30):
        _cited(me, f"c{i}.jpg")
    objs = [_old(key(me, f"c{i}.jpg")) for i in range(30)] + [_old(key(me, "o.jpg"))]
    assert _sweep(objs)[0] == 1
    assert _sweep([o for o in objs if "o.jpg" not in o[0]])[0] == 0           # the bucket no longer lists it
    # the same listing at an earlier clock: the object is inside its grace, so it waits
    assert _sweep(objs, now=NOW - timedelta(days=3))[0] == 0


@pytest.mark.django_db
def test_an_empty_bucket_and_the_dev_stub_sweep_nothing():
    assert _sweep([])[0] == 0
    # No bucket configured: the real lister yields nothing, and the sweep is a no-op.
    assert sweep_orphan_story_uploads(now=NOW) == 0


# ---- telemetry and the command --------------------------------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_the_sweep_emits_one_event_with_a_count_and_none_when_there_was_nothing(caplog):
    me = AccountFactory()
    with caplog.at_level(logging.INFO, logger="kupkop.analytics"):
        _sweep([_old(key(me, "a.jpg"))])
        _sweep([])
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "kupkop.analytics"]
    swept = [e for e in events if e["event"] == "story_orphans_swept"]
    assert len(swept) == 1 and swept[0]["count"] == 1
    assert not {"account_id", "key", "url"} & set(swept[0])


@pytest.mark.django_db
def test_the_command_runs_the_sweep(capsys):
    from django.core.management import call_command
    with mock.patch("community.management.commands.sweep_story_uploads.sweep_orphan_story_uploads", return_value=4) as sweep:
        call_command("sweep_story_uploads")
    sweep.assert_called_once()
    assert "4" in capsys.readouterr().out


# ---- the real lister, against a mocked bucket ---------------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_real_lister_and_deleter_against_a_bucket(settings):
    settings.MEDIA_S3_BUCKET_PUBLIC = "kupkop-media-public-test"
    me = AccountFactory()
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=settings.MEDIA_S3_BUCKET_PUBLIC)
        kept, orphan = key(me, "kept.jpg"), key(me, "orphan.jpg")
        for k in (kept, orphan, f"pet_photo/{me.pk}/p.jpg"):
            s3.put_object(Bucket=settings.MEDIA_S3_BUCKET_PUBLIC, Key=k, Body=b"x")
        for i in range(30):                                    # enough cited keys that one orphan is a normal night, not a refusal
            s3.put_object(Bucket=settings.MEDIA_S3_BUCKET_PUBLIC, Key=key(me, f"c{i}.jpg"), Body=b"x")
            _cited(me, f"c{i}.jpg")
        _cited(me, "kept.jpg")
        # A fresh object is inside its grace, so nothing goes tonight; a day and an hour on, only the orphan does.
        assert sweep_orphan_story_uploads(now=timezone.now()) == 0
        later = timezone.now() + timedelta(hours=ORPHAN_GRACE_HOURS + 1)
        assert sweep_orphan_story_uploads(now=later) == 1
        left = {o["Key"] for o in s3.list_objects_v2(Bucket=settings.MEDIA_S3_BUCKET_PUBLIC).get("Contents", [])}
        assert orphan not in left and kept in left and f"pet_photo/{me.pk}/p.jpg" in left
