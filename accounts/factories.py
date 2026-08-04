import factory

from accounts.models import Account, AccountSettings


class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account
        skip_postgeneration_save = True

    account_type = "personal"
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    display_name = "Test User"

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or "s3cretpass")
        if create:
            obj.save()

    @factory.post_generation
    def with_settings(obj, create, extracted, **kwargs):
        if create:
            AccountSettings.objects.get_or_create(account=obj)


class AccountSettingsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccountSettings
        # AccountFactory already creates a settings row per account (its
        # with_settings post_generation hook), so a plain create() here would
        # collide with the OneToOne unique constraint. get_or_create keyed on
        # `account` returns that existing row for a fresh SubFactory account,
        # or lets an explicitly-passed existing account's settings be fetched.
        django_get_or_create = ("account",)

    account = factory.SubFactory(AccountFactory)
