import pytest
from django.core.management import call_command

from accounts.factories import AccountFactory
from accounts.models import Account, StaffProfile
from accounts.staff import reviewer_account


@pytest.mark.django_db
def test_reviewer_account_returns_linked_admin_account(django_user_model):
    # Option A: a staff Django User is linked 1:1 to an admin Account, which is what
    # reviewed_by points at. reviewer_account() resolves the User to that Account.
    account = AccountFactory(account_type="admin")
    user = django_user_model.objects.create_superuser("rita", "rita@kupkop.ph", "pw")
    StaffProfile.objects.create(user=user, account=account)
    assert reviewer_account(user) == account


@pytest.mark.django_db
def test_reviewer_account_is_none_when_user_unlinked(django_user_model):
    # A superuser with no linked admin Account cannot be attributed — the caller must
    # treat None as a setup error rather than stamping an anonymous decision.
    user = django_user_model.objects.create_superuser("nolink", "nolink@kupkop.ph", "pw")
    assert reviewer_account(user) is None


@pytest.mark.django_db
def test_createstaff_creates_user_admin_account_and_link(django_user_model):
    call_command("createstaff", email="rev@kupkop.ph", username="rev",
                 password="reviewerpw", display_name="Rev One")
    user = django_user_model.objects.get(username="rev")
    assert user.is_staff and user.is_superuser
    account = Account.objects.get(email="rev@kupkop.ph")
    assert account.account_type == "admin"
    # the bridge is wired, so a decision this staffer makes can be attributed
    assert reviewer_account(user) == account


@pytest.mark.django_db
def test_createstaff_is_idempotent_on_rerun(django_user_model):
    call_command("createstaff", email="rev@kupkop.ph", username="rev",
                 password="reviewerpw", display_name="Rev One")
    call_command("createstaff", email="rev@kupkop.ph", username="rev",
                 password="reviewerpw", display_name="Rev One")
    assert django_user_model.objects.filter(username="rev").count() == 1
    assert Account.objects.filter(email="rev@kupkop.ph").count() == 1
    assert StaffProfile.objects.count() == 1
