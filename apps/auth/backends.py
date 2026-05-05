"""Authentication backend that accepts phone OR email as the identifier.

Used by Django session login (the /admin/ panel) and as a fallback for
DRF Session auth. The OTP flow does not call this backend — it mints
JWTs via apps.auth.services.issue_token_pair.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from core.validators import normalize_phone

User = get_user_model()


class PhoneOrEmailBackend(ModelBackend):
    def authenticate(self, request, username: str | None = None, password: str | None = None, **kwargs):
        if username is None or password is None:
            return None
        user = self._lookup(username)
        if user is None:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    @staticmethod
    def _lookup(identifier: str):
        if "@" in identifier:
            return User.objects.filter(email__iexact=identifier).first()
        try:
            normalized = normalize_phone(identifier)
        except Exception:
            return None
        return User.objects.filter(phone=normalized).first()
