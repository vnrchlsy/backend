"""US-M1 · "Report this" on a stray report or listing."""
import pytest

from accounts.factories import AccountFactory
from accounts.tokens import tokens_for
from moderation.models import FlagStatus, ModerationFlag


def _hdr(acc):
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens_for(acc)['access']}"}


@pytest.mark.django_db
def test_creates_a_flag(client):
    acc = AccountFactory()
    target = AccountFactory()
    res = client.post("/api/v1/moderation/flags",
                      {"target_type": "account", "target_id": str(target.pk),
                       "reason": "Spam messages"}, **_hdr(acc))
    assert res.status_code == 201
    flag = ModerationFlag.objects.get(pk=res.json()["flag_id"])
    assert flag.reporter_account_id == acc.pk
    assert flag.target_type == "account"
    assert str(flag.target_id) == str(target.pk)
    assert flag.status == FlagStatus.OPEN


@pytest.mark.django_db
def test_guest_is_refused(client):
    res = client.post("/api/v1/moderation/flags",
                      {"target_type": "listing", "target_id": "00000000-0000-0000-0000-000000000000",
                       "reason": "x"})
    assert res.status_code == 401


@pytest.mark.django_db
def test_a_second_open_flag_on_the_same_target_by_the_same_account_collapses(client):
    acc = AccountFactory()
    target_id = "00000000-0000-0000-0000-000000000001"
    first = client.post("/api/v1/moderation/flags",
                        {"target_type": "listing", "target_id": target_id, "reason": "Fake listing"},
                        **_hdr(acc))
    second = client.post("/api/v1/moderation/flags",
                         {"target_type": "listing", "target_id": target_id, "reason": "Still fake"},
                         **_hdr(acc))
    assert second.status_code == 200
    assert second.json()["flag_id"] == first.json()["flag_id"]
    assert ModerationFlag.objects.filter(target_id=target_id).count() == 1


@pytest.mark.django_db
def test_a_different_account_flagging_the_same_target_is_a_separate_flag(client):
    target_id = "00000000-0000-0000-0000-000000000002"
    a, b = AccountFactory(), AccountFactory()
    res_a = client.post("/api/v1/moderation/flags",
                        {"target_type": "report", "target_id": target_id, "reason": "x"}, **_hdr(a))
    res_b = client.post("/api/v1/moderation/flags",
                        {"target_type": "report", "target_id": target_id, "reason": "y"}, **_hdr(b))
    assert res_a.status_code == 201 and res_b.status_code == 201
    assert res_a.json()["flag_id"] != res_b.json()["flag_id"]


@pytest.mark.django_db
def test_flagging_again_after_the_earlier_flag_was_resolved_opens_a_fresh_one(client):
    acc = AccountFactory()
    target_id = "00000000-0000-0000-0000-000000000003"
    first = client.post("/api/v1/moderation/flags",
                        {"target_type": "report", "target_id": target_id, "reason": "first"},
                        **_hdr(acc))
    ModerationFlag.objects.filter(pk=first.json()["flag_id"]).update(status=FlagStatus.DISMISSED)

    second = client.post("/api/v1/moderation/flags",
                         {"target_type": "report", "target_id": target_id, "reason": "again"},
                         **_hdr(acc))
    assert second.status_code == 201
    assert second.json()["flag_id"] != first.json()["flag_id"]
    assert ModerationFlag.objects.filter(target_id=target_id).count() == 2


@pytest.mark.django_db
def test_an_unknown_target_type_is_refused(client):
    acc = AccountFactory()
    res = client.post("/api/v1/moderation/flags",
                      {"target_type": "carrier_pigeon",
                       "target_id": "00000000-0000-0000-0000-000000000000", "reason": "x"},
                      **_hdr(acc))
    assert res.status_code == 400
