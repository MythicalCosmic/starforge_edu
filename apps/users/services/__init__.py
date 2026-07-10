"""User-side write services."""

from __future__ import annotations

import random
import secrets
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.users.models import Device
from core.exceptions import ValidationException
from core.validators import normalize_phone

_NAME_MAX = 150  # User first/last/middle_name column length

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
        # This email becomes the account's unique login identifier — validate its
        # format and length up front rather than persisting junk (or 500ing on a
        # >254-char value that overflows the column).
        email = email.lower().strip()
        try:
            validate_email(email)
        except DjangoValidationError:
            raise ValidationException(
                _("Enter a valid email address."),
                code="validation_error",
                fields={"email": ["Enter a valid email address."]},
            ) from None
        lookup = {"email": email}
    else:
        raise ValidationException(_("phone or email is required."), code="identifier_required")
    for field, value in (("first_name", first_name), ("last_name", last_name), ("middle_name", middle_name)):
        if len(value) > _NAME_MAX:
            raise ValidationException(
                _("Name is too long."),
                code="validation_error",
                fields={field: [f"Must be at most {_NAME_MAX} characters."]},
            )
    user = User.objects.filter(**lookup).first()
    if user is None:
        user = User.objects.create(
            username=User.objects.generate_username(
                email or "", (phone or "").lstrip("+"), f"{first_name}.{last_name}"
            ),
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            **lookup,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def bump_token_version(user_id: int) -> None:
    """Invalidate every live access token for a user (TD-1 `tv` claim)."""
    User.objects.filter(pk=user_id).update(token_version=F("token_version") + 1)


def set_user_password(user: User, raw_password: str) -> None:
    """Set a password and end EVERY existing session: all outstanding refresh
    tokens are blacklisted and `tv` is bumped so live access tokens die too.
    (Review fix: a tv bump alone left stolen refreshes valid for 14 days.)"""
    user.set_password(raw_password)
    user.save(update_fields=["password"])
    # Lazy import: apps.auth.services imports from this module (circular otherwise).
    from apps.auth.services import logout_everywhere

    logout_everywhere(user)


# Unambiguous alphabet for one-time passwords (no 0/O/1/I/l) — easy to read aloud/type.
_TEMP_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
_TEMP_DIGITS = "23456789"


def generate_temp_password(length: int = 10) -> str:
    """A readable, strong one-time password (>=1 digit + letters -> clears the password
    validators; drops ambiguous characters for easy typing/hand-off)."""
    length = max(length, 8)
    chars = [secrets.choice(_TEMP_LETTERS) for _ in range(length - 2)]
    chars.append(secrets.choice(_TEMP_DIGITS))
    chars.append(secrets.choice(_TEMP_LETTERS))
    random.SystemRandom().shuffle(chars)
    return "".join(chars)


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
    # Truncate to the column bounds (device_id 128, platform 16) so a long client
    # value never 500s mid-login — mirrors core.session_auth.create_session.
    device_id, platform = device_id[:128], platform[:16]
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
