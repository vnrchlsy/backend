from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # US-SEC3 · every staff admin login now needs a verified TOTP device, not just a
        # password. "django.contrib.admin" sits first in INSTALLED_APPS, so its own
        # ready() (which registers every ModelAdmin via autodiscover) has already run by
        # the time this app's ready() fires — swapping the class of the already-populated
        # singleton is the documented django-otp pattern and keeps every existing
        # admin.site.register() call working unchanged.
        from django.contrib import admin
        from django_otp.admin import OTPAdminSite

        admin.site.__class__ = OTPAdminSite
