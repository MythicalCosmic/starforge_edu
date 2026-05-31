"""Auth orchestration: send/verify OTP, issue/refresh JWT pairs."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db import connection, transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.auth.authentication import TENANT_CLAIM
from apps.users.models import OTP
from core.exceptions import ThrottledException, ValidationException
from core.utils import generate_otp
from core.validators import normalize_phone
from infrastructure.email.email_client import send_email
from infrastructure.sms.eskiz_client import get_sms_client

User = get_user_model()


def _channel_for(identifier: str) -> str:
    return OTP.CHANNEL_EMAIL if "@" in identifier else OTP.CHANNEL_SMS


def _normalize(identifier: str) -> str:
    if "@" in identifier:
        return identifier.lower().strip()
    return normalize_phone(identifier)


@transaction.atomic
def send_otp(*, identifier: str, purpose: str = OTP.PURPOSE_LOGIN) -> OTP:
    """Generate, store (hashed), and dispatch an OTP."""

    identifier = _normalize(identifier)
    channel = _channel_for(identifier)

    code = generate_otp(settings.OTP_LENGTH)
    otp = OTP.objects.create(
        identifier=identifier,
        channel=channel,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )

    if channel == OTP.CHANNEL_SMS:
        get_sms_client().send(
            phone=identifier,
            text=f"Starforge code: {code}. Valid for {settings.OTP_TTL_SECONDS // 60} min.",
        )
    else:
        send_email(
            to=identifier,
            subject="Starforge login code",
            body=f"Your code is {code}. Valid for {settings.OTP_TTL_SECONDS // 60} minutes.",
        )

    return otp


def verify_otp(*, identifier: str, code: str, purpose: str = OTP.PURPOSE_LOGIN) -> User:
    """Verify the OTP, mark consumed, return (creating if needed) the User."""

    identifier = _normalize(identifier)

    # Critical section: lock the OTP row, record the attempt, and on success
    # mark it consumed. This atomic block must COMMIT even when the code is
    # wrong — otherwise the `attempts` increment would roll back on every
    # failure and OTP_MAX_ATTEMPTS would never trigger (brute-force counter
    # would be a no-op). So we raise for an invalid code *after* the block.
    with transaction.atomic():
        otp = (
            OTP.objects.select_for_update()
            .filter(
                identifier=identifier,
                purpose=purpose,
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if otp is None:
            raise ValidationException("Code expired or never issued. Request a new one.")
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise ThrottledException("Too many attempts. Request a new code.")

        otp.attempts += 1
        is_valid = check_password(code, otp.code_hash)
        if is_valid:
            otp.consumed_at = timezone.now()
            otp.save(update_fields=["attempts", "consumed_at"])
        else:
            otp.save(update_fields=["attempts"])

    if not is_valid:
        raise ValidationException("Invalid code.")

    with transaction.atomic():
        if "@" in identifier:
            user, _ = User.objects.get_or_create(email=identifier)
        else:
            user, _ = User.objects.get_or_create(phone=identifier)

        if not user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password"])

        user.last_seen_at = timezone.now()
        user.save(update_fields=["last_seen_at"])
    return user


def issue_token_pair(user) -> dict[str, str]:
    """Mint an access+refresh pair via simplejwt, bound to the active tenant.

    The ``tenant_schema`` claim is copied onto the derived access token and is
    enforced by ``TenantBoundJWTAuthentication`` so a token cannot be replayed
    against a different Center.
    """

    refresh = RefreshToken.for_user(user)
    # django-tenants sets schema_name dynamically on the connection.
    refresh[TENANT_CLAIM] = getattr(connection, "schema_name", None)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}
