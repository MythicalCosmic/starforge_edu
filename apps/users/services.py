"""User-side write services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.users.models import Device
from core.exceptions import ValidationException
from core.validators import normalize_phone

if TYPE_CHECKING:
    from apps.users.models import User
else:
    User = get_user_model()


def resolve_or_create_user(
    *,
    phone: str = "",
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
) -> User:
    """Find (or create, passwordless) a User by phone/email. Shared by the
    student/teacher creation services so identity handling stays in one place."""
    if phone:
        lookup = {"phone": normalize_phone(phone)}
    elif email:
        lookup = {"email": email.lower().strip()}
    else:
        raise ValidationException(_("phone or email is required."), code="identifier_required")
    user, created = User.objects.get_or_create(
        **lookup,
        defaults={"first_name": first_name, "last_name": last_name, "middle_name": middle_name},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


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


def bump_token_version(user_id: int) -> None:
    """Invalidate every live access token for a user (TD-1 `tv` claim)."""
    User.objects.filter(pk=user_id).update(token_version=F("token_version") + 1)


def set_user_password(user: User, raw_password: str) -> None:
    """Set a password and invalidate existing sessions (D1-LC-7 hook)."""
    user.set_password(raw_password)
    user.save(update_fields=["password"])
    bump_token_version(user.pk)


def register_device(
    *,
    user: User,
    device_id: str,
    platform: str,
    user_agent: str = "",
    push_token: str = "",
) -> Device | None:
    """Upsert a Device on login / push-token registration. No-op without both
    a stable `device_id` and a `platform`."""
    if not device_id or not platform:
        return None
    defaults: dict[str, object] = {
        "platform": platform,
        "user_agent": user_agent,
        "last_seen_at": timezone.now(),
        "revoked_at": None,
    }
    if push_token:
        defaults["push_token"] = push_token
    device, _created = Device.objects.update_or_create(user=user, device_id=device_id, defaults=defaults)
    return device
