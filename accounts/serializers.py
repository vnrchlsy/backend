from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken as SimpleRefreshToken

from accounts.models import Account, AccountType


class SignupSerializer(serializers.Serializer):
    # Public signup may only create "personal" or "shelter" accounts.
    # "admin" (in AccountType.choices) must never be reachable from here.
    account_type = serializers.ChoiceField(choices=[("personal", "personal"), ("shelter", "shelter")])
    display_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        if Account.objects.filter(email=value).exists():
            raise serializers.ValidationError("email_taken", code="email_taken")
        return value


def account_repr(account):
    return {
        "account_id": str(account.account_id),
        "account_type": account.account_type,
        "display_name": account.display_name,
        "email": account.email,
        "email_verified_at": account.email_verified_at,
        "phone": account.phone,
        "phone_verified_at": account.phone_verified_at,
        "photo_url": account.photo_url or None,
    }


def me_repr(account):
    rel = getattr(account, "capabilities", None)
    caps = [{"capability": c.capability, "status": c.status} for c in rel.all()] if rel else []
    s = account.settings
    return {**account_repr(account), "capabilities": caps, "shelter": None,
            "settings": {"marketing_emails": s.marketing_emails,
                         "approximate_location": s.approximate_location,
                         "masked_contact": s.masked_contact, "push_enabled": s.push_enabled}}


class MeUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=100, required=False)
    photo_file_url = serializers.CharField(required=False, allow_blank=True)


class MeSettingsSerializer(serializers.Serializer):
    marketing_emails = serializers.BooleanField(required=False)
    approximate_location = serializers.BooleanField(required=False)
    masked_contact = serializers.BooleanField(required=False)
    push_enabled = serializers.BooleanField(required=False)


class EmailVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField()


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField()
    new_password = serializers.CharField(min_length=8)


class AccountTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = SimpleRefreshToken(attrs["refresh"])
        account = Account.objects.filter(account_id=token.get("account_id")).first()
        if account is None:
            raise InvalidToken("account_not_found")
        if (account.sessions_revoked_at
                and int(token["iat"]) <= int(account.sessions_revoked_at.timestamp())):
            raise InvalidToken("session_revoked")
        return super().validate(attrs)
