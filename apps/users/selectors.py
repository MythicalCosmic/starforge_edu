"""Read-side selectors for users."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from core.validators import normalize_phone

User = get_user_model()


def find_by_identifier(identifier: str) -> User | None:
    if "@" in identifier:
        return User.objects.filter(email__iexact=identifier).first()
    try:
        normalized = normalize_phone(identifier)
    except Exception:
        return None
    return User.objects.filter(phone=normalized).first()
