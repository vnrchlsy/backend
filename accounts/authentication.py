from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from accounts.models import Account


class AccountJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        account = Account.objects.filter(account_id=validated_token["account_id"]).first()
        if account is None:
            raise InvalidToken("account_not_found")
        revoked = account.sessions_revoked_at
        iat = validated_token.get("iat")
        if revoked is not None and iat is not None and int(iat) <= int(revoked.timestamp()):
            raise InvalidToken("session_revoked")
        return account
