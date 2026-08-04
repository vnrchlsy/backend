from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.models import Account
from accounts.serializers import (AccountTokenRefreshSerializer, EmailSerializer, EmailVerifySerializer,
                                  MeSettingsSerializer, MeUpdateSerializer, SignupSerializer, account_repr, me_repr)
from accounts.tokens import tokens_for
from common import otp
from common.otp import CodeExpired, CodeInvalid, CodeLocked, issue_code, verify_code
from common.throttles import OtpResendHourThrottle, OtpResendMinuteThrottle


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if not serializer.is_valid():
            email_errors = serializer.errors.get("email")
            if email_errors and getattr(email_errors[0], "code", None) == "email_taken":
                return Response(
                    {"error": {"code": "email_taken", "message": "Email already in use",
                               "field": "email"}}, status=status.HTTP_409_CONFLICT)
            return Response({"error": {"code": "invalid", "message": "Invalid input",
                                       "details": serializer.errors}}, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        try:
            account = Account.objects.create_account(
                account_type=data["account_type"], email=data["email"],
                password=data["password"], display_name=data["display_name"])
        except IntegrityError:
            return Response(
                {"error": {"code": "email_taken", "message": "Email already in use",
                           "field": "email"}}, status=status.HTTP_409_CONFLICT)
        otp.issue_code(account, channel="email", purpose="signup")
        return Response({"account_id": str(account.account_id), "email": account.email,
                         "next": "verify_email"}, status=status.HTTP_201_CREATED)


def _otp_error_response(exc):
    if isinstance(exc, CodeLocked):
        return Response({"error": {"code": "code_locked", "message": "Too many attempts"}}, status=423)
    if isinstance(exc, CodeExpired):
        return Response({"error": {"code": "code_expired", "message": "Code expired"}}, status=410)
    return Response({"error": {"code": "code_invalid", "message": "Invalid code",
                               "details": {"attempts_left": exc.attempts_left}}}, status=400)


class EmailVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = EmailVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        account = Account.objects.filter(email=s.validated_data["email"]).first()
        if account is None:
            # Mirror the response a real account gets on its first wrong-code
            # attempt (attempts_left = OTP_MAX_ATTEMPTS - 1) so a single probe
            # can't distinguish "no such account" from "account exists, code
            # just hasn't been guessed yet".
            return _otp_error_response(CodeInvalid(attempts_left=settings.OTP_MAX_ATTEMPTS - 1))
        try:
            verify_code(account, purpose="signup", code=s.validated_data["code"])
        except (CodeInvalid, CodeExpired, CodeLocked) as exc:
            return _otp_error_response(exc)
        if account.email_verified_at is None:
            account.email_verified_at = timezone.now()
            account.save(update_fields=["email_verified_at"])
        return Response({**tokens_for(account), "account": account_repr(account)})


class EmailResendView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OtpResendMinuteThrottle, OtpResendHourThrottle]

    def post(self, request):
        s = EmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        account = Account.objects.filter(email=s.validated_data["email"]).first()
        if account is not None and account.email_verified_at is None:
            issue_code(account, channel="email", purpose="signup")
        return Response({}, status=202)   # generic regardless


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email", "")
        password = request.data.get("password", "")
        account = Account.objects.filter(email=email).first()
        if account is None or not account.check_password(password):
            return Response({"error": {"code": "invalid_credentials",
                                       "message": "Email or password is incorrect"}}, status=401)
        if account.email_verified_at is None:
            issue_code(account, channel="email", purpose="signup")
            return Response({"error": {"code": "email_unverified",
                                       "message": "Verify your email"}}, status=403)
        return Response({**tokens_for(account), "account": account_repr(account)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            RefreshToken(request.data["refresh"]).blacklist()
        except Exception:
            pass
        return Response(status=204)


class LogoutAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.user.sessions_revoked_at = timezone.now()
        request.user.save(update_fields=["sessions_revoked_at"])
        return Response(status=204)


class AccountTokenRefreshView(TokenRefreshView):
    serializer_class = AccountTokenRefreshSerializer


class PasswordForgotView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OtpResendMinuteThrottle, OtpResendHourThrottle]

    def post(self, request):
        s = EmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        account = Account.objects.filter(email=s.validated_data["email"]).first()
        if account is not None:
            issue_code(account, channel="email", purpose="reset")
        return Response({})   # always generic


class PasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from accounts.serializers import PasswordResetSerializer
        s = PasswordResetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        account = Account.objects.filter(email=s.validated_data["email"]).first()
        if account is None:
            # Mirror the response a real account gets on its first wrong-code
            # attempt so a single probe can't distinguish "no such account"
            # from "account exists, code just hasn't been guessed yet".
            return _otp_error_response(CodeInvalid(attempts_left=settings.OTP_MAX_ATTEMPTS - 1))
        try:
            verify_code(account, purpose="reset", code=s.validated_data["code"])
        except (CodeInvalid, CodeExpired, CodeLocked) as exc:
            return _otp_error_response(exc)
        account.set_password(s.validated_data["new_password"])
        account.sessions_revoked_at = timezone.now()   # revoke all existing sessions (Task 6 mechanism)
        account.save(update_fields=["password_hash", "sessions_revoked_at"])
        return Response({})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(me_repr(request.user))

    def patch(self, request):
        acc = request.user
        s = MeUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if "display_name" in s.validated_data:
            acc.display_name = s.validated_data["display_name"]
        if "photo_file_url" in s.validated_data:
            acc.photo_url = s.validated_data["photo_file_url"]
        acc.save()
        return Response(me_repr(acc))


class MeSettingsView(APIView):
    permission_classes = [IsAuthenticated]
    FIELDS = ["marketing_emails", "approximate_location", "masked_contact", "push_enabled"]

    def get(self, request):
        s = request.user.settings
        return Response({f: getattr(s, f) for f in self.FIELDS})

    def patch(self, request):
        s = request.user.settings
        serializer = MeSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for key, value in serializer.validated_data.items():
            setattr(s, key, value)
        s.save()
        return Response({f: getattr(s, f) for f in self.FIELDS})


class MeLocationView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        from accounts.models import Address
        city = request.data.get("city")
        barangay = request.data.get("barangay", "")
        if not city:
            return Response({"error": {"code": "invalid", "message": "city required",
                                       "field": "city"}}, status=400)
        addr, _ = Address.objects.get_or_create(account=request.user, is_primary=True,
                                                defaults={"city": city})
        addr.city = city
        addr.barangay = barangay
        addr.geom = None
        addr.save()
        return Response({"city": addr.city, "barangay": addr.barangay or None})


class SocialAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, provider):
        from accounts.models import AccountIdentity
        from accounts import social
        claims = social.verify_token(provider, request.data.get("id_token"))
        email = claims.get("email")
        if not email:
            return Response({"error": {"code": "email_required",
                                       "message": "This provider did not share an email address"}},
                            status=400)
        sub = claims["sub"]
        identity = AccountIdentity.objects.filter(provider=provider, provider_user_id=sub).first()
        is_new = False
        if identity:
            account = identity.account
        else:
            account = Account.objects.filter(email=email).first()
            if account is None:
                at = request.data.get("account_type", "personal")
                if at not in ("personal", "shelter"):
                    at = "personal"
                account = Account.objects.create_account(
                    account_type=at,
                    email=email, display_name=email.split("@")[0], password=None)
                account.email_verified_at = timezone.now()
                account.save(update_fields=["email_verified_at"])
                is_new = True
            AccountIdentity.objects.create(account=account, provider=provider,
                                           provider_user_id=sub, email=email)
        return Response({**tokens_for(account), "is_new": is_new,
                         "account": account_repr(account)})
