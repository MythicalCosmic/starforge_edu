"""Throttle classes for auth endpoints.

Login (username+password):
- LoginUserThrottle: per username. 5 req/min default (scope ``login_user``).
- LoginIPThrottle:   per remote address. 10 req/min default (scope ``login_ip``).

OTP (password reset / verification):
- OTPIdentifierThrottle: per NORMALIZED identifier, request endpoint only.
  3 req/min default (scope ``otp_phone``). Normalization closes the
  format-variation bypass (+998..., 998..., spaced digits → one bucket).
- OTPVerifyThrottle: per identifier on the confirm endpoint, its own scope
  (``otp_verify``) so verification attempts never cannibalize the request
  budget — the OTP.attempts cap is the real brute-force control there.
- OTPIPThrottle / OTPGlobalThrottle: per-IP and global caps.

Rates are configured in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] in
config/settings/base.py. All identifier-keyed throttles coerce non-string
payloads defensively — throttles run before serializer validation.
"""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle

from core.utils import current_schema
from core.validators import normalize_phone


def _normalized_identifier(request) -> str | None:
    identifier = request.data.get("identifier") if hasattr(request, "data") else None
    if not isinstance(identifier, str) or not identifier:
        return None
    if "@" in identifier:
        return identifier.lower().strip()
    try:
        return normalize_phone(identifier)
    except Exception:
        return identifier.lower().strip()


class LoginUserThrottle(SimpleRateThrottle):
    scope = "login_user"

    def get_cache_key(self, request, view):
        username = request.data.get("username") if hasattr(request, "data") else None
        if not isinstance(username, str) or not username:
            return None
        # Schema-scoped: usernames are unique per tenant, so an attack on tenant
        # A's "admin" must not exhaust tenant B's "admin" bucket (shared Redis).
        return f"login_user:{current_schema()}:{username.strip().lower()}"


class LoginIPThrottle(SimpleRateThrottle):
    scope = "login_ip"

    def get_cache_key(self, request, view):
        return f"login_ip:{self.get_ident(request)}"


class OTPIdentifierThrottle(SimpleRateThrottle):
    scope = "otp_phone"

    def get_cache_key(self, request, view):
        identifier = _normalized_identifier(request)
        if identifier is None:
            return None
        # Schema-scoped like LoginUserThrottle: a reset OTP targets a user in THIS
        # tenant, so an attack on tenant A's phone X must not exhaust tenant B's
        # bucket for the same phone (shared cache). otp_ip/otp_global still bound
        # cross-tenant abuse.
        return f"otp_phone:{current_schema()}:{identifier}"


class OTPVerifyThrottle(SimpleRateThrottle):
    scope = "otp_verify"

    def get_cache_key(self, request, view):
        identifier = _normalized_identifier(request)
        if identifier is None:
            return None
        return f"otp_verify:{current_schema()}:{identifier}"


class OTPIPThrottle(SimpleRateThrottle):
    scope = "otp_ip"

    def get_cache_key(self, request, view):
        return f"otp_ip:{self.get_ident(request)}"


class OTPGlobalThrottle(SimpleRateThrottle):
    scope = "otp_global"

    def get_cache_key(self, request, view):
        return "otp_global"
