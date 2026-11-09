"""Stories review step 8 (ST8, SQ4) · a story has bounds, a photo order, and exactly one primary photo.

Before, a 200,000-character caption and 200 photos, all marked primary, were accepted (201), photo order was whatever Postgres returned (there was no position
column), and nothing held a story to one primary photo. Now: a caption of at most 2,000 characters (SQ4, owner), 1 to 6 photos, each photo's `position`, and exactly one
primary photo, held by the database as well as the writer.
"""
import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from community.models import StoryPhoto, StoryPost

URL = "/api/v1/stories"


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def own(acc, name="a.jpg"):
    return f"https://bkt.example/story_photo/{acc.pk}/{name}"


def _post(client, acc, **body):
    body.setdefault("photos", [{"file_url": own(acc)}])
    return client.post(URL, body, content_type="application/json", **_hdr(acc))


def _photos(acc, n, primary=None):
    return [{"file_url": own(acc, f"{i}.jpg"), **({} if primary is None else {"is_primary": i == primary})} for i in range(n)]


# ── the caption ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_caption_of_2000_characters_is_fine_and_2001_is_refused(client):
    me = AccountFactory()
    assert _post(client, me, caption="a" * 2000).status_code == 201
    res = _post(client, me, caption="a" * 2001)
    assert res.status_code == 400 and res.json()["error"]["field"] == "caption"
    assert "2,000" in res.json()["error"]["message"]                                      # a sentence, not DRF's default
    assert StoryPost.objects.filter(author_account=me).count() == 1


@pytest.mark.django_db
def test_the_limit_counts_characters_not_bytes_and_ignores_outer_whitespace(client):
    me = AccountFactory()
    assert _post(client, me, caption="🐶" * 2000).status_code == 201                       # 2,000 characters, 8,000 bytes
    assert _post(client, me, caption="  " + "b" * 2000 + "  ").status_code == 201          # the server trims first


@pytest.mark.django_db
def test_editing_a_caption_has_the_same_limit(client):
    me = AccountFactory()
    s = StoryPost.objects.create(author_account=me, story_type="general", caption="x")
    StoryPhoto.objects.create(story=s, url=own(me), is_primary=True)
    ok = client.patch(f"{URL}/{s.pk}", {"caption": "c" * 2000}, content_type="application/json", **_hdr(me))
    assert ok.status_code == 200
    bad = client.patch(f"{URL}/{s.pk}", {"caption": "c" * 2001}, content_type="application/json", **_hdr(me))
    assert bad.status_code == 400 and bad.json()["error"]["field"] == "caption"
    s.refresh_from_db()
    assert len(s.caption) == 2000


# ── how many photos ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
@pytest.mark.parametrize("n", [1, 3, 6])
def test_one_to_six_photos_are_fine(client, n):
    me = AccountFactory()
    res = _post(client, me, photos=_photos(me, n))
    assert res.status_code == 201
    assert StoryPhoto.objects.filter(story_id=res.json()["story_id"]).count() == n


@pytest.mark.django_db
def test_seven_photos_are_refused_and_nothing_is_written(client):
    me = AccountFactory()
    res = _post(client, me, photos=_photos(me, 7))
    assert res.status_code == 400 and res.json()["error"]["field"] == "photos"
    assert "6" in res.json()["error"]["message"]
    assert not StoryPost.objects.exists() and not StoryPhoto.objects.exists()


@pytest.mark.django_db
def test_two_hundred_photos_are_refused_without_checking_each(client):
    me = AccountFactory()
    res = _post(client, me, photos=[{"file_url": own(me, f"{i}.jpg"), "is_primary": True} for i in range(200)])
    assert res.status_code == 400 and not StoryPost.objects.exists()


@pytest.mark.django_db
def test_no_photos_is_still_photo_required(client):
    res = _post(client, AccountFactory(), photos=[])
    assert res.status_code == 422 and res.json()["error"]["code"] == "photo_required"


@pytest.mark.django_db
def test_the_same_photo_twice_is_refused(client):
    me = AccountFactory()
    res = _post(client, me, photos=[{"file_url": own(me, "a.jpg")}, {"file_url": own(me, "a.jpg")}])
    assert res.status_code == 400 and res.json()["error"]["field"] == "photos"
    assert not StoryPost.objects.exists()


# ── order and the one primary ───────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_photos_keep_the_order_they_were_sent_in(client):
    me = AccountFactory()
    res = _post(client, me, photos=_photos(me, 4))
    rows = list(StoryPhoto.objects.filter(story_id=res.json()["story_id"]).order_by("position"))
    assert [p.position for p in rows] == [0, 1, 2, 3]
    assert [p.url for p in rows] == [own(me, f"{i}.jpg") for i in range(4)]


@pytest.mark.django_db
def test_with_no_primary_marked_the_first_photo_is_primary(client):
    me = AccountFactory()
    sid = _post(client, me, photos=_photos(me, 3)).json()["story_id"]
    assert list(StoryPhoto.objects.filter(story_id=sid, is_primary=True).values_list("position", flat=True)) == [0]


@pytest.mark.django_db
def test_the_marked_photo_is_the_primary_and_the_order_is_still_the_order_sent(client):
    me = AccountFactory()
    sid = _post(client, me, photos=_photos(me, 3, primary=2)).json()["story_id"]
    assert list(StoryPhoto.objects.filter(story_id=sid, is_primary=True).values_list("position", flat=True)) == [2]
    row = client.get(f"{URL}/{sid}").json()
    assert row["primary_photo"] == own(me, "2.jpg") and row["photos"][0]["url"] == own(me, "2.jpg")      # the primary leads...
    assert [p["url"] for p in row["photos"][1:]] == [own(me, "0.jpg"), own(me, "1.jpg")]                 # ...the rest in sent order


@pytest.mark.django_db
def test_two_primaries_marked_is_refused(client):
    me = AccountFactory()
    res = _post(client, me, photos=[{"file_url": own(me, "a.jpg"), "is_primary": True}, {"file_url": own(me, "b.jpg"), "is_primary": True}])
    assert res.status_code == 400 and res.json()["error"]["field"] == "photos"
    assert not StoryPost.objects.exists()


@pytest.mark.django_db
def test_the_database_holds_one_primary_per_story():
    me = AccountFactory()
    s = StoryPost.objects.create(author_account=me, story_type="general")
    StoryPhoto.objects.create(story=s, url=own(me, "a.jpg"), is_primary=True, position=0)
    with pytest.raises(IntegrityError), transaction.atomic():
        StoryPhoto.objects.create(story=s, url=own(me, "b.jpg"), is_primary=True, position=1)
    StoryPhoto.objects.create(story=s, url=own(me, "c.jpg"), is_primary=False, position=1)          # any number of non-primaries
    other = StoryPost.objects.create(author_account=me, story_type="general")
    StoryPhoto.objects.create(story=other, url=own(me, "d.jpg"), is_primary=True, position=0)        # one per story, not one overall


@pytest.mark.django_db
def test_a_read_orders_the_photos_the_same_every_time_even_with_equal_positions(client):
    me = AccountFactory()
    s = StoryPost.objects.create(author_account=me, story_type="general")
    for i in range(5):
        StoryPhoto.objects.create(story=s, url=own(me, f"{i}.jpg"), is_primary=(i == 0))              # positions all default 0
    assert len({tuple(p["url"] for p in client.get(f"{URL}/{s.pk}").json()["photos"]) for _ in range(5)}) == 1


# ── the migration (0017): positions and one primary for stories that already exist ──────────────
BEFORE, AFTER = ("community", "0016_story_removed"), ("community", "0017_story_photo_position")


@pytest.mark.django_db(transaction=True)
def test_the_migration_gives_existing_photos_a_position_and_every_story_one_primary():
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE])
    try:
        old = executor.loader.project_state([BEFORE]).apps
        Post, Photo = old.get_model("community", "StoryPost"), old.get_model("community", "StoryPhoto")
        author = AccountFactory()
        def story(marks):
            s = Post.objects.create(author_account_id=author.pk, story_type="general")
            for i, primary in enumerate(marks):
                Photo.objects.create(story_id=s.pk, url=f"https://x/{s.pk}/{i}", is_primary=primary)
            return s.pk
        none_marked, two_marked, one_marked, no_photos = story([False, False, False]), story([True, True, False]), story([False, True]), story([])

        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])
        new = executor.loader.project_state([AFTER]).apps
        Photo = new.get_model("community", "StoryPhoto")
        for sid, expected_n in ((none_marked, 3), (two_marked, 3), (one_marked, 2), (no_photos, 0)):
            rows = list(Photo.objects.filter(story_id=sid).order_by("position"))
            assert [r.position for r in rows] == list(range(expected_n))                     # 0..n-1, no ties
            assert sum(r.is_primary for r in rows) == (1 if expected_n else 0)               # exactly one, none for none
        assert next(r for r in Photo.objects.filter(story_id=one_marked) if r.is_primary).position == 0   # the marked one, now first
    finally:
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
