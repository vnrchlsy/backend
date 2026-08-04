from rest_framework_simplejwt.tokens import RefreshToken


def tokens_for(account):
    refresh = RefreshToken()
    refresh["account_id"] = str(account.account_id)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}
