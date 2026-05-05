"""Throttle classes for OTP endpoints — three-layer defense.

- OTPPhoneThrottle: per identifier (phone or email). 3 req/min default.
- OTPIPThrottle:    per remote address. 10 req/min default.
- OTPGlobalThrottle: global cap. 1000 req/hour default.

Rates are configured in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] in
config/settings/base.py.
"""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class OTPPhoneThrottle(SimpleRateThrottle):
    scope = "otp_phone"

    def get_cache_key(self, request, view):
        identifier = request.data.get("identifier") if hasattr(request, "data") else None
        if not identifier:
            return None
        return f"otp_phone:{identifier.lower()}"


class OTPIPThrottle(SimpleRateThrottle):
    scope = "otp_ip"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return f"otp_ip:{ident}"


class OTPGlobalThrottle(SimpleRateThrottle):
    scope = "otp_global"

    def get_cache_key(self, request, view):
        return "otp_global"
