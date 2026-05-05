"""User-side write services."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from core.validators import normalize_phone

User = get_user_model()


def get_or_create_by_identifier(identifier: str) -> tuple[User, bool]:
    """Look up a user by phone or email, creating a passwordless one if absent."""

    if "@" in identifier:
        user, created = User.objects.get_or_create(email=identifier.lower())
    else:
        user, created = User.objects.get_or_create(phone=normalize_phone(identifier))
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user, created
