"""TD-1: bind every JWT to the tenant that minted it.

A token issued in tenant A carries ``schema="A"``; presenting it on tenant B's
host is rejected with 401 ``tenant_mismatch``. A token whose ``tv`` no longer
equals the user's ``token_version`` (password change, role grant/revoke,
logout-everywhere) is rejected with 401 ``token_stale``. This closes the
cross-tenant replay hole and gives instant global invalidation.

The authenticator also opportunistically touches ``last_seen_at`` (D1-LC-12)
with a single throttled UPDATE.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.utils import current_schema

LAST_SEEN_STALE_SECONDS = 60


class TenantAwareJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        # Lazy import: this module is loaded while DRF resolves
        # DEFAULT_AUTHENTICATION_CLASSES, before core.exceptions is safe to pull.
        from core.exceptions import AuthenticationException

        header = self.get_header(request)
        if header is None:
            return None
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None
        validated_token = self.get_validated_token(raw_token)

        # Tenant binding MUST be checked BEFORE the user lookup. A cross-tenant
        # token's user_id row does not exist in this schema, so get_user() would
        # raise `user_not_found` first and the mismatch would never surface — the
        # whole point of TD-1 is the `tenant_mismatch` signal.
        if validated_token.get("schema") != current_schema():
            raise AuthenticationException(
                _("This token was issued for a different center."), code="tenant_mismatch"
            )

        user = self.get_user(validated_token)

        if validated_token.get("tv") != getattr(user, "token_version", None):
            raise AuthenticationException(
                _("Your session is no longer valid. Please sign in again."), code="token_stale"
            )

        self._touch_last_seen(user)
        return user, validated_token

    @staticmethod
    def _touch_last_seen(user) -> None:
        now = timezone.now()
        last = getattr(user, "last_seen_at", None)
        if last is None or (now - last) > timedelta(seconds=LAST_SEEN_STALE_SECONDS):
            # One UPDATE, no auto_now churn / signals; refresh the in-memory copy.
            type(user).objects.filter(pk=user.pk).update(last_seen_at=now)
            user.last_seen_at = now
