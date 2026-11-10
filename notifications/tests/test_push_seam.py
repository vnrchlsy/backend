"""US-P2 · the Expo send seam (notifications review NP1, NQ1). The transport is always patched: no test
reaches the network."""
from unittest.mock import patch

import pytest
import requests

from notifications import push

TOK = "ExponentPushToken[abcDEF123]"


@pytest.fixture
def on(settings):
    settings.EXPO_PUSH_ENABLED = "1"
    settings.EXPO_PUSH_ACCESS_TOKEN = ""


def _ok(n=1):
    return 200, {"data": [{"status": "ok", "id": f"r{i}"} for i in range(n)]}


def test_unconfigured_is_noop(settings):
    settings.EXPO_PUSH_ENABLED = ""
    with patch.object(push, "_expo_transport") as tx:
        r = push.send_push(TOK, title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is False and not tx.called


def test_success_sends_one_well_formed_message(on):
    with patch.object(push, "_expo_transport", return_value=_ok()) as tx:
        r = push.send_push(TOK, title="hi", body="b", data={"shift_id": "s"})
    assert r.ok is True and r.unregistered is False
    (messages,), _ = tx.call_args
    assert messages == [{"to": TOK, "title": "hi", "body": "b", "data": {"shift_id": "s"},
                         "sound": "default", "priority": "high"}]


def test_device_not_registered_marks_the_token_dead(on):
    t = {"data": [{"status": "error", "message": "x", "details": {"error": "DeviceNotRegistered"}}]}
    with patch.object(push, "_expo_transport", return_value=(200, t)):
        r = push.send_push(TOK, title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is True


@pytest.mark.parametrize("code", ["MessageTooBig", "MessageRateExceeded", "InvalidCredentials", None])
def test_other_refusals_fail_without_pruning(on, code):
    t = {"data": [{"status": "error", "details": {"error": code} if code else {}}]}
    with patch.object(push, "_expo_transport", return_value=(200, t)):
        r = push.send_push(TOK, title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is False


@pytest.mark.parametrize("answer", [
    (500, None), (429, {"errors": []}), (200, None), (200, "nope"), (200, {"data": "x"}),
    (200, {"data": []}), (200, {"data": [{"status": "ok"}, {"status": "ok"}]}),
])
def test_an_unusable_answer_fails_and_prunes_nothing(on, answer):
    with patch.object(push, "_expo_transport", return_value=answer):
        r = push.send_push(TOK, title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is False


@pytest.mark.parametrize("exc", [requests.Timeout(), requests.ConnectionError(), ValueError("boom")])
def test_a_transport_error_never_propagates(on, exc):
    with patch.object(push, "_expo_transport", side_effect=exc):
        r = push.send_push(TOK, title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is False


@pytest.mark.parametrize("token", ["", "t1", "fcm:APA91b...", "ExponentPushToken[]", "ExponentPushToken[a b]",
                                   "ExponentPushToken[ok]x", None, 7])
def test_a_token_expo_could_never_deliver_is_reported_dead_without_a_call(on, token):
    with patch.object(push, "_expo_transport") as tx:
        r = push.send_push(token, title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is True and not tx.called


def test_a_batch_is_split_at_100_and_results_keep_their_order(on):
    items = [(f"ExponentPushToken[t{i}]", "t", "b", {}) for i in range(230)]
    sizes = []

    def fake(messages):
        sizes.append(len(messages))
        return _ok(len(messages))

    with patch.object(push, "_expo_transport", side_effect=fake):
        results = push.send_push_batch(items)
    assert sizes == [100, 100, 30] and len(results) == 230 and all(r.ok for r in results)


def test_a_batch_mixes_outcomes_per_item(on):
    items = [(TOK, "t", "b", {}), ("junk", "t", "b", {}), ("ExponentPushToken[dead]", "t", "b", {})]
    tickets = {"data": [{"status": "ok"}, {"status": "error", "details": {"error": "DeviceNotRegistered"}}]}
    with patch.object(push, "_expo_transport", return_value=(200, tickets)) as tx:
        r = push.send_push_batch(items)
    assert [(x.ok, x.unregistered) for x in r] == [(True, False), (False, True), (False, True)]
    assert len(tx.call_args[0][0]) == 2          # the junk token never reached Expo


def test_one_failed_chunk_does_not_stop_the_next(on):
    items = [(f"ExponentPushToken[t{i}]", "t", "b", {}) for i in range(150)]
    answers = iter([requests.Timeout(), _ok(50)])

    def fake(messages):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    with patch.object(push, "_expo_transport", side_effect=fake):
        r = push.send_push_batch(items)
    assert [x.ok for x in r[:100]] == [False] * 100 and [x.ok for x in r[100:]] == [True] * 50


def test_the_access_token_is_sent_only_when_set(on, settings):
    seen = {}

    class R:
        status_code = 200
        def json(self): return {"data": [{"status": "ok"}]}

    def post(url, json, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return R()

    with patch.object(push.requests, "post", side_effect=post):
        push._expo_transport([{"to": TOK}])
        assert "Authorization" not in seen["headers"]
        settings.EXPO_PUSH_ACCESS_TOKEN = "sekret"
        push._expo_transport([{"to": TOK}])
    assert seen["headers"]["Authorization"] == "Bearer sekret"
    assert seen["url"] == push.EXPO_PUSH_URL and seen["timeout"] == push.EXPO_TIMEOUT_SECONDS
