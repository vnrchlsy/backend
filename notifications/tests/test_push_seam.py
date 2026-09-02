from unittest.mock import patch

from notifications import push


def test_unconfigured_is_noop(settings):
    settings.FCM_PROJECT_ID = ""
    r = push.send_push("tok", title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is False   # no-op sender: nothing sent


def test_configured_success(settings):
    settings.FCM_PROJECT_ID = "proj"; settings.FCM_CREDENTIALS_PATH = "/x"
    with patch.object(push, "_fcm_transport", return_value={"status": 200}) as tx:
        r = push.send_push("tok", title="hi", body="b", data={"shift_id": "s"})
    assert r.ok is True and r.unregistered is False and tx.called


def test_configured_unregistered(settings):
    settings.FCM_PROJECT_ID = "proj"; settings.FCM_CREDENTIALS_PATH = "/x"
    with patch.object(push, "_fcm_transport", return_value={"status": 404, "error": "UNREGISTERED"}):
        r = push.send_push("dead", title="hi", body="b", data={})
    assert r.ok is False and r.unregistered is True
