import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me-in-production-0123456789")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

# The platform ops surface (US-R1) runs on the built-in Django admin: staff (Kupkop
# reviewers) authenticate against contrib.auth.User over a web SESSION — deliberately
# separate from the app's JWT/Account identity, which the mobile clients use. The admin,
# sessions and messages apps carry the reviewer surface; the domain apps below are the API.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",   # Sagip (US-S1) uses PostGIS: PointField + spatial queries
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "accounts",
    "verifications",
    "listings",
    "shelter",
    "notifications",
    "sagip",
]

# SecurityMiddleware + CommonMiddleware served the JWT API alone in Sprint 1. The admin
# adds the session/auth/csrf/message/clickjacking stack. DRF's APIViews are csrf_exempt
# (they use JWT, not SessionAuthentication), so CsrfViewMiddleware does not touch the API.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates",
             "DIRS": [], "APP_DIRS": True, "OPTIONS": {"context_processors": [
                 "django.template.context_processors.request",
                 "django.contrib.auth.context_processors.auth",
                 "django.contrib.messages.context_processors.messages",
             ]}}]

# NOTE: this is a localhost-only dev slice, not a real DATABASE_URL parser.
# We only ever read the DB name (the last "/"-separated segment) out of
# DATABASE_URL and always connect to HOST "localhost" below. Any host,
# user, password, or port encoded in a non-localhost DATABASE_URL is
# intentionally ignored here. Proper URL parsing (e.g. dj-database-url)
# is deferred until we need to point at a non-local Postgres instance.
DATABASES = {
    "default": {
        # PostGIS backend from Sprint 2 on: stray_report.geom is a real geography(Point)
        # and US-S4's map is a proximity query. The postgis backend is a superset of the
        # plain postgresql one, so every existing app keeps working. Requires the PostGIS
        # extension, enabled by the sagip 0001 migration (dev + CI + staging).
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("DATABASE_URL", "postgres://localhost/kupkop_dev").rsplit("/", 1)[-1],
        "HOST": "localhost",
        "TEST": {"NAME": os.environ.get("TEST_DATABASE_NAME", "kupkop_test")},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.AccountJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    # US-SEC2 · policy numbers, not code constants — revisit with real traffic data.
    "DEFAULT_THROTTLE_RATES": {
        "otp_resend_min": "1/min", "otp_resend_hour": "5/hour",
        "login_ip": "20/hour", "login_identifier": "10/hour",
        "signup_ip": "10/hour",
        "password_forgot_ip": "20/hour", "password_forgot_identifier": "10/hour",
        "report_create": "20/day", "offer_create": "20/hour",
    },
    "EXCEPTION_HANDLER": "common.errors.error_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "USER_ID_FIELD": "account_id",
    "USER_ID_CLAIM": "account_id",
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
# Version of the Terms/Privacy text a signup consents to (RA 10173 — recorded on
# account.terms_consent_version). Bump whenever the user-facing terms change, so an
# older consent is distinguishable from consent to the current text.
TERMS_VERSION = "2026-08-01"
