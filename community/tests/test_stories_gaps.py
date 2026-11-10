"""Stories test plan (dev/test-plan-stories.md) · the partial rows that a backend test can close: NT-3 (I4), NT-4 (I9), NT-5 (F4), NT-6 (F1), NT-7 (U8).

These were written to find out, not to confirm: each one states what the review expected, and the test is what the code actually does.
"""
import logging
import threading

import pytest
from django.db import OperationalError, connection
from django.test import Client

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from community.models import StoryPhoto, StoryPost, StoryStatus
from moderation.actions import resolve_flag
from moderation.models import FlagStatus, ModerationFlag
from notifications.models import Notification

URL = "/api/v1/stories"


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


def own(acc, name="a.jpg"):
    return f"https://bkt.example/story_photo/{acc.pk}/{name}"


def _story(author, status=StoryStatus.PUBLISHED, caption="Home at last"):
    s = StoryPost.objects.create(author_account=author, story_type="general", caption=caption, status=status)
    StoryPhoto.objects.create(story=s, url=own(author, f"{s.pk}.jpg"), is_primary=True, position=0)
    return s


def _post(client, acc, **body):
    body.setdefault("photos", [{"file_url": own(acc)}])
    return client.post(URL, body, content_type="application/json", **_hdr(acc))


# ---- NT-7 · U8 · a refused caption is logged by field, never by text ----------------------------------------------------------
@pytest.mark.django_db
def test_a_refused_caption_is_logged_by_its_field_and_the_text_is_in_no_log_line(client, caplog):
    me = AccountFactory()
    text = "what a fucker"
    with caplog.at_level(logging.DEBUG):                          # every logger, every level
        res = _post(client, me, caption=text)
    assert res.status_code == 400 and res.json()["error"]["details"].get("caption")
    lines = [r.getMessage() for r in caplog.records]
    assert any("invalid_caption" in line for line in lines)       # the field is named
    assert not any(text in line or "fucker" in line for line in lines)
    assert StoryPost.objects.count() == 0


# ---- NT-3 · I4 · a database error on the feed is the error envelope, not an internals page -------------------------------------
@pytest.mark.django_db
def test_a_database_error_on_the_feed_is_a_json_500_with_no_internals(caplog):
    _story(AccountFactory())
    seen = {"n": 0}

    def drop_second_query(execute, sql, params, many, context):
        seen["n"] += 1
        if seen["n"] == 2:
            raise OperationalError("server closed the connection unexpectedly")
        return execute(sql, params, many, context)

    with caplog.at_level(logging.ERROR, logger="django.request"), connection.execute_wrapper(drop_second_query):
        res = Client(raise_request_exception=False).get(URL)
    assert res.status_code == 500
    assert res["Content-Type"].startswith("application/json"), res.content[:120]
    assert res.json()["error"]["code"] == "server_error"
    assert "server closed" not in res.content.decode()


# ---- NT-6 · F1 · hostile payloads ---------------------------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_body_past_the_size_limit_is_refused_and_writes_nothing(client):
    me = AccountFactory()
    big = '{"caption": "' + "a" * (6 * 1024 * 1024) + '", "photos": []}'          # 6 MB against DATA_UPLOAD_MAX_MEMORY_SIZE of 5 MB
    res = client.post(URL, big, content_type="application/json", **_hdr(me))
    assert res.status_code == 400, res.status_code
    assert StoryPost.objects.count() == 0
    # FOUND (test plan NT-14): Django refuses the body before DRF runs, so the answer is its HTML "Bad Request" page, not the JSON error envelope
    # every other refusal uses. The app's client reads a non-JSON 400 as a failed call, so nothing breaks; it is recorded, not pinned.


@pytest.mark.django_db
def test_nested_junk_in_photos_is_a_400_and_writes_nothing(client):
    me = AccountFactory()
    junk = [[[[]]], {"file_url": {"a": {"b": 1}}}, {"file_url": ["x"]}, {"file_url": None}, 5, "x", None]
    for photos in (junk, [junk], {"file_url": own(me)}, "x"):
        res = _post(client, me, photos=photos)
        assert res.status_code in (400, 422), (photos, res.status_code)
    assert StoryPost.objects.count() == 0


@pytest.mark.django_db
def test_a_caption_of_control_characters_never_becomes_a_500(client):
    me = AccountFactory()
    for caption in ("\x00" * 10, "a\x00b", "\x01\x02\x03\x1b[31m", "‮" * 50, "퟿" * 20):
        res = _post(client, me, caption=caption)
        assert res.status_code < 500, (repr(caption), res.status_code, res.content[:120])
    # FOUND: NUL is refused with a message on `caption` (400); other control characters and bidi overrides are accepted as text. Whatever was accepted holds no NUL.
    assert not any("\x00" in s.caption for s in StoryPost.objects.all())


# ---- NT-5 · F4 · an author's delete and a moderator's hide, at the same moment ----------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_a_delete_and_a_takedown_racing_always_end_removed():
    from moderation.targets import _hide_story
    for _ in range(8):
        author = AccountFactory()
        s = _story(author)
        start, out = threading.Barrier(2), {}

        def delete():
            try:
                start.wait()
                out["delete"] = Client().delete(f"{URL}/{s.pk}", **_hdr(author)).status_code
            finally:
                connection.close()

        def hide():
            try:
                start.wait()
                out["hide"] = _hide_story(StoryPost.objects.get(pk=s.pk), reviewer=None, reason="")
            finally:
                connection.close()

        threads = [threading.Thread(target=delete), threading.Thread(target=hide)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        s.refresh_from_db()
        assert out["delete"] == 204, out                      # the author's delete lands whichever came first
        assert s.status == StoryStatus.REMOVED and s.removed_at is not None, out
        assert out["hide"] in (True, False)                   # never an exception


# ---- NT-4 · I9 · the whole moderation round trip, as one story -------------------------------------------------------------------
@pytest.mark.django_db
def test_report_hide_notice_open_restore_notice(client):
    from community.moderation import restore_story
    author, stranger, reporter, staff = (AccountFactory() for _ in range(4))
    s = _story(author)
    assert [r["story_id"] for r in client.get(URL).json()["results"]] == [str(s.pk)]

    # report → the staff action hides it
    flag = ModerationFlag.objects.create(reporter_account=reporter, target_type="story", target_id=s.pk, reason="x", status="open")
    resolve_flag(flag, staff, FlagStatus.ACTIONED, reason_code="spam_scam")
    s.refresh_from_db()
    assert s.status == StoryStatus.HIDDEN and s.hidden_at is not None

    # the feed drops it, a stranger cannot open it, the author is told and can open it from the notice and from Your stories
    assert client.get(URL).json()["results"] == []
    assert client.get(f"{URL}/{s.pk}", **_hdr(stranger)).status_code == 404
    note = Notification.objects.get(account=author, type="story_removed")
    assert note.data == {"story_id": str(s.pk)}
    opened = client.get(f"{URL}/{note.data['story_id']}", **_hdr(author))
    assert opened.status_code == 200 and opened.json()["status"] == "hidden"
    mine = client.get("/api/v1/me/stories", **_hdr(author)).json()["results"]
    assert [(m["story_id"], m["status"]) for m in mine] == [(str(s.pk), "hidden")]

    # staff restores it: back on the feed, the author is told, and it opens as published
    restore_story(s, staff, "Flagged in error.")
    assert [r["story_id"] for r in client.get(URL).json()["results"]] == [str(s.pk)]
    back = Notification.objects.get(account=author, type="story_restored")
    assert back.data == {"story_id": str(s.pk)}
    assert client.get(f"{URL}/{back.data['story_id']}", **_hdr(author)).json()["status"] == "published"
    s.refresh_from_db()
    assert s.restored_at is not None and s.hidden_at is not None
