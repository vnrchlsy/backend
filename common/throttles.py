from rest_framework.throttling import SimpleRateThrottle


class OtpResendMinuteThrottle(SimpleRateThrottle):
    scope = "otp_resend_min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class OtpResendHourThrottle(SimpleRateThrottle):
    scope = "otp_resend_hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
