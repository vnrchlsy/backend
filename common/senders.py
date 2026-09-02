import logging

from django.conf import settings

logger = logging.getLogger("kupkop.otp")


class Sender:
    def send(self, *, channel, to, code):
        raise NotImplementedError


class ConsoleSender(Sender):
    def send(self, *, channel, to, code):
        masked = to[:2] + "***"
        logger.info("OTP via %s to %s (code hidden in logs)", channel, masked)
        # DEV ONLY: with no real email/SMS provider, print the raw code locally so
        # the code can be entered during development. Gated on DEBUG — never in prod.
        if settings.DEBUG:
            print(f"[DEV OTP] {channel} {to}: {code}", flush=True)


def get_sender():
    return ConsoleSender()
