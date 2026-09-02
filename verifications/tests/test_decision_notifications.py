"""US-X1 — every verification decision tells the applicant (in-app row this sprint)."""
import pytest

from accounts.factories import AccountFactory
from notifications.models import Notification
from verifications.models import VerificationRequest
from verifications.review import approve_request, reject_request, request_more_info


def _reviewer():
    return AccountFactory(account_type="admin", email="rev@kupkop.ph")


def _request():
    return VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")


@pytest.mark.django_db
def test_approve_writes_an_approved_notification_to_the_applicant():
    vr = _request()
    approve_request(vr, _reviewer())
    n = Notification.objects.get(account=vr.account)
    assert n.type == "verification_approved"
    assert n.data["verification_id"] == str(vr.verification_id)
    assert n.read is False


@pytest.mark.django_db
def test_reject_notification_carries_the_reason_the_applicant_acts_on():
    vr = _request()
    reject_request(vr, _reviewer(), "Billing photo is unreadable.")
    n = Notification.objects.get(account=vr.account)
    assert n.type == "verification_rejected"
    assert "Billing photo is unreadable." in n.body


@pytest.mark.django_db
def test_needs_info_notification_carries_the_ask():
    vr = _request()
    request_more_info(vr, _reviewer(), "Please replace the billing photo.")
    n = Notification.objects.get(account=vr.account)
    assert n.type == "verification_needs_info"
    assert "Please replace the billing photo." in n.body


@pytest.mark.django_db
def test_a_refused_decision_writes_no_notification():
    from verifications.review import ReviewError
    vr = _request()
    with pytest.raises(ReviewError):
        reject_request(vr, _reviewer(), "")  # empty reason refused
    assert not Notification.objects.filter(account=vr.account).exists()
