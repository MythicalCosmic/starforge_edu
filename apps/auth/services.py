"""Auth orchestration: send/verify OTP, issue/refresh JWT pairs."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from apps.auth.signals import otp_failed, otp_requested, otp_verified
from apps.users.models import OTP
from apps.users.services import bump_token_version
from core.exceptions import AuthenticationException, ThrottledException, ValidationException
from core.utils import current_schema, generate_otp
from core.validators import normalize_phone
from infrastructure.email.email_client import send_email
from infrastructure.sms.eskiz_client import get_sms_client

if TYPE_CHECKING:
    from apps.users.models import User
else:
    User = get_user_model()


def _on_public_schema() -> bool:
    from django_tenants.utils import get_public_schema_name

    return current_schema() == get_public_schema_name()


def _registration_open() -> bool:
    """Whether an unknown identifier may self-register on OTP verify (TD-17).

    Reads `CenterSettings.open_registration` inside a tenant; on the public
    schema (platform staff, no CenterSettings table) it falls back to the
    `OPEN_REGISTRATION_DEFAULT` platform setting (default off)."""
    if _on_public_schema():
        return bool(getattr(settings, "OPEN_REGISTRATION_DEFAULT", False))
    from apps.org.selectors import get_center_settings

    return bool(get_center_settings().open_registration)


def _otp_cooldown_seconds() -> int:
    """Resend cooldown — `CenterSettings.otp_cooldown_seconds` per tenant, the
    `OTP_COOLDOWN_SECONDS` setting on the public schema."""
    if _on_public_schema():
        return int(getattr(settings, "OTP_COOLDOWN_SECONDS", 60))
    from apps.org.selectors import get_center_settings

    return int(get_center_settings().otp_cooldown_seconds)


def _channel_for(identifier: str) -> str:
    return OTP.CHANNEL_EMAIL if "@" in identifier else OTP.CHANNEL_SMS


def _normalize(identifier: str) -> str:
    if "@" in identifier:
        return identifier.lower().strip()
    return normalize_phone(identifier)


def _enforce_cooldown(identifier: str) -> None:
    since = timezone.now() - timedelta(seconds=_otp_cooldown_seconds())
    if OTP.objects.filter(identifier=identifier, created_at__gt=since).exists():
        raise ThrottledException(_("Please wait before requesting another code."))


def _enforce_ip_cap(ip: str, identifier: str) -> None:
    """Reject when one IP fans out across too many distinct identifiers per hour."""
    if not ip:
        return
    cap = int(getattr(settings, "OTP_IP_DISTINCT_IDENTIFIER_CAP", 5))
    key = f"otp_ip_idents:{ip}"
    identifiers = set(cache.get(key) or [])
    identifiers.add(identifier)
    cache.set(key, list(identifiers), timeout=3600)
    if len(identifiers) > cap:
        raise ThrottledException(_("Too many login attempts from your network."))


@transaction.atomic
def send_otp(
    *,
    identifier: str,
    purpose: str = OTP.PURPOSE_LOGIN,
    ip: str = "",
    user_agent: str = "",
) -> OTP:
    """Generate, store (hashed), and dispatch an OTP. Cooldown + per-IP capped."""

    identifier = _normalize(identifier)
    channel = _channel_for(identifier)

    _enforce_cooldown(identifier)
    _enforce_ip_cap(ip, identifier)

    code = generate_otp(settings.OTP_LENGTH)
    otp = OTP.objects.create(
        identifier=identifier,
        channel=channel,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )

    # External dispatch is grandfathered inline for auth OTP (CODE-GUIDE §6).
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

    schema = current_schema()
    transaction.on_commit(
        lambda: otp_requested.send(
            sender=OTP, identifier=identifier, ip=ip, user_agent=user_agent, schema_name=schema
        )
    )
    return otp


def verify_otp(
    *,
    identifier: str,
    code: str,
    purpose: str = OTP.PURPOSE_LOGIN,
    ip: str = "",
    user_agent: str = "",
) -> User:
    """Verify the OTP, mark consumed, and return the existing (or newly
    self-registered) User. Failed attempts are persisted so the max-attempts
    cap actually bites — the increment is committed before any exception."""

    identifier = _normalize(identifier)

    # Lock + evaluate the candidate OTP. We exit the atomic block normally on a
    # wrong code (committing the attempts++), then raise — so a brute-force
    # streak is recorded instead of being rolled back with the exception.
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
            _fire_failed(identifier, ip, user_agent, reason="no_active_code")
            raise ValidationException(_("Code expired or never issued. Request a new one."))

        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            _fire_failed(identifier, ip, user_agent, reason="too_many_attempts")
            raise ThrottledException(_("Too many attempts. Request a new code."))

        otp.attempts += 1
        correct = check_password(code, otp.code_hash)
        if correct:
            otp.consumed_at = timezone.now()
            otp.save(update_fields=["attempts", "consumed_at"])
        else:
            otp.save(update_fields=["attempts"])

    if not correct:
        _fire_failed(identifier, ip, user_agent, reason="wrong_code")
        raise ValidationException(_("Invalid code."))

    user = _resolve_user(identifier)

    user.last_seen_at = timezone.now()
    user.save(update_fields=["last_seen_at"])

    otp_verified.send(
        sender=OTP,
        identifier=identifier,
        ip=ip,
        user_agent=user_agent,
        schema_name=current_schema(),
    )
    return user


def _resolve_user(identifier: str) -> User:
    lookup = {"email": identifier} if "@" in identifier else {"phone": identifier}
    user = User.objects.filter(**lookup).first()
    if user is None:
        # TD-17: never auto-create unless the Center opened registration.
        if not _registration_open():
            raise ValidationException(_("No account found for this identifier."), code="user_not_found")
        user = User.objects.create(**lookup)
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _fire_failed(identifier: str, ip: str, user_agent: str, *, reason: str) -> None:
    otp_failed.send(
        sender=OTP,
        identifier=identifier,
        ip=ip,
        user_agent=user_agent,
        reason=reason,
        schema_name=current_schema(),
    )


def _token_claims(user: User) -> dict[str, object]:
    """TD-1/TD-5 claims baked into both access and refresh tokens."""
    roles = list(
        user.role_memberships.filter(revoked_at__isnull=True).values_list("role", flat=True).distinct()
    )
    return {
        "schema": current_schema(),
        "tv": user.token_version,
        "roles": roles,
    }


def issue_token_pair(user: User) -> dict[str, str]:
    """Mint an access+refresh pair via simplejwt, both carrying TD-1 claims."""

    refresh = RefreshToken.for_user(user)
    access = refresh.access_token
    claims = _token_claims(user)
    for token in (refresh, access):
        for key, value in claims.items():
            token[key] = value
    return {"access": str(access), "refresh": str(refresh)}


def rotate_refresh_token(raw_refresh: str) -> dict[str, str]:
    """Rotate a refresh token: blacklist the old, mint a fresh pair (with TD-1
    claims). Presenting an already-blacklisted token is treated as theft —
    every session for that user is revoked and 401 ``refresh_reused`` raised."""
    try:
        refresh = RefreshToken(raw_refresh)  # type: ignore[arg-type]
    except TokenError as exc:
        _detect_refresh_reuse(raw_refresh)  # raises refresh_reused if it is reuse
        raise AuthenticationException(
            _("Invalid or expired refresh token."), code="authentication_failed"
        ) from exc

    user = User.objects.filter(pk=refresh.get("user_id")).first()
    if user is None:
        raise AuthenticationException(_("Invalid or expired refresh token."), code="authentication_failed")

    refresh.blacklist()
    return issue_token_pair(user)


def _detect_refresh_reuse(raw_refresh: str) -> None:
    """If `raw_refresh` is a syntactically valid token whose jti is already
    blacklisted, this is a replay — revoke all of that user's tokens."""
    try:
        token = UntypedToken(raw_refresh)  # type: ignore[arg-type]  # signature + exp only
    except TokenError:
        return
    jti = token.get("jti")
    user_id = token.get("user_id")
    if not jti or not user_id:
        return
    if BlacklistedToken.objects.filter(token__jti=jti).exists():
        _revoke_all_refresh_tokens(user_id)
        bump_token_version(user_id)
        raise AuthenticationException(_("Refresh token reuse detected."), code="refresh_reused")


def _revoke_all_refresh_tokens(user_id: int) -> None:
    for outstanding in OutstandingToken.objects.filter(user_id=user_id):
        BlacklistedToken.objects.get_or_create(token=outstanding)


def logout_everywhere(user: User) -> None:
    """Blacklist every outstanding refresh for the user and bump `tv` so live
    access tokens die too (D1-LC-8)."""
    _revoke_all_refresh_tokens(user.pk)
    bump_token_version(user.pk)
