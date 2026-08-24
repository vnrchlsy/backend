"""US-SEC3 · viewing a verification request's detail page (where identity documents
render — see VerificationRequestAdmin.documents_preview) writes an audit row. Decisions
were already attributable (reviewed_by/_at); this covers *views*.
"""
import pytest

from accounts.factories import AccountFactory
from accounts.models import StaffProfile
from verifications.models import VerificationAccessLog, VerificationRequest

CHANGE = "/admin/verifications/verificationrequest/{}/change/"
CHANGELIST = "/admin/verifications/verificationrequest/"


def _request():
    return VerificationRequest.objects.create(account=AccountFactory(), type="shelter_org")


@pytest.mark.django_db
def test_viewing_the_detail_page_writes_an_access_log_row(admin_client, admin_user):
    vr = _request()
    admin_client.get(CHANGE.format(vr.pk))

    row = VerificationAccessLog.objects.get(verification=vr)
    assert row.staff_username == admin_user.get_username()
    assert row.viewed_at is not None


@pytest.mark.django_db
def test_access_log_resolves_the_reviewer_account_via_the_staff_bridge(admin_client, admin_user):
    account = AccountFactory(account_type="admin", email=admin_user.email or "rev@kupkop.ph")
    StaffProfile.objects.create(user=admin_user, account=account)
    vr = _request()

    admin_client.get(CHANGE.format(vr.pk))

    row = VerificationAccessLog.objects.get(verification=vr)
    assert row.viewer == account


@pytest.mark.django_db
def test_access_log_still_attributes_a_view_with_no_staff_bridge_link(admin_client, admin_user):
    # admin_user (pytest-django's default superuser) has no StaffProfile by default —
    # the view must still be recorded, just with viewer=None.
    vr = _request()
    admin_client.get(CHANGE.format(vr.pk))

    row = VerificationAccessLog.objects.get(verification=vr)
    assert row.viewer is None
    assert row.staff_username


@pytest.mark.django_db
def test_each_view_writes_its_own_row(admin_client):
    vr = _request()
    admin_client.get(CHANGE.format(vr.pk))
    admin_client.get(CHANGE.format(vr.pk))
    assert VerificationAccessLog.objects.filter(verification=vr).count() == 2


@pytest.mark.django_db
def test_viewing_the_changelist_does_not_write_a_row(admin_client):
    _request()
    admin_client.get(CHANGELIST)
    assert VerificationAccessLog.objects.count() == 0


@pytest.mark.django_db
def test_a_missing_object_id_does_not_crash_or_log(admin_client):
    import uuid

    # Django's admin redirects to the changelist with an error message for an unknown
    # object_id rather than raising — the guard in change_view must not break that.
    res = admin_client.get(CHANGE.format(uuid.uuid4()))
    assert res.status_code == 302
    assert VerificationAccessLog.objects.count() == 0


@pytest.mark.django_db
def test_non_staff_cannot_view_and_writes_no_row(client, django_user_model):
    vr = _request()
    user = django_user_model.objects.create_user("bob", password="irrelevant")
    client.force_login(user)
    res = client.get(CHANGE.format(vr.pk))
    assert res.status_code == 302
    assert VerificationAccessLog.objects.count() == 0
