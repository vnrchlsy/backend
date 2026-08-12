"""Onboard a Kupkop reviewer (US-R1).

Creates the two linked identities Option A needs: a Django `contrib.auth.User` (the
`/admin` login) and an `Account(account_type='admin')` (what `reviewed_by` points at),
joined by a `StaffProfile`. Idempotent — safe to re-run to reset a password or repair a
missing link.

    python manage.py createstaff --email rev@kupkop.ph --username rev \
        --password '…' --display-name 'Rev One'
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Account, AccountType, StaffProfile


class Command(BaseCommand):
    help = "Create or update a Kupkop reviewer: a Django superuser linked to an admin Account."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--username", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--display-name", dest="display_name", default="")

    @transaction.atomic
    def handle(self, *, email, username, password, display_name, **opts):
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_staff": True, "is_superuser": True})
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        account, _ = Account.objects.get_or_create(
            email=email,
            defaults={"account_type": AccountType.ADMIN,
                      "display_name": display_name or username})
        if account.account_type != AccountType.ADMIN:
            account.account_type = AccountType.ADMIN
            account.save(update_fields=["account_type"])

        StaffProfile.objects.get_or_create(user=user, defaults={"account": account})
        self.stdout.write(self.style.SUCCESS(f"Reviewer ready: {username} <{email}>"))
