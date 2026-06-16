"""Auth orchestration: username+password login, JWT pairs, password reset via OTP.

Owner decision (2026-06-11): login is username + password. OTP codes are no
longer a login mechanism — they serve password reset (and, later, contact
verification). JWTs carry TD-1 claims (`schema`, `tv`, `roles`) on both the
access and refresh tokens, and every refresh-path operation is tenant-bound.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from apps.auth.signals import login_failed, login_succeeded, otp_failed, otp_requested, otp_verified
from apps.users.models import OTP
from apps.users.services import bump_token_version, set_user_password
from core.exceptions import (
    AuthenticationException,
    StarforgeError,
    StrOrPromise,
    ThrottledException,
    ValidationException,
)
from core.utils import current_schema, generate_otp
from core.validators import normalize_phone
from infrastructure.email.email_client import send_email
from infrastructure.sms.eskiz_client import get_sms_client

if TYPE_CHECKING:
    from apps.users.models import User
else:
    User = get_user_model()

# Computed once; used to equalize timing when the username does not exist so
# login responses don't reveal which usernames are registered.
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = make_password("starforge-timing-equalizer")
    return _DUMMY_HASH


# ---------------------------------------------------------------------------
# Login (username + password)
# ---------------------------------------------------------------------------


def login_with_password(*, username: str, password: str, ip: str = "", user_agent: str = "") -> User:
    """Authenticate username+password and return the User.

    Failures are indistinguishable to the caller (401 ``invalid_credentials``
    for unknown username, wrong password, and inactive account alike) and a
    dummy hash check keeps the unknown-username path timing-equivalent.
    """
    username = username.strip()
    user = User.objects.filter(username=username).first()
    if user is None:
        check_password(password, _dummy_hash())  # constant-time-ish equalizer
        _fire_login_failed(username, ip, user_agent, reason="unknown_username")
        raise AuthenticationException(_("Invalid username or password."), code="invalid_credentials")

    if not user.check_password(password) or not user.is_active:
        reason = "wrong_password" if user.is_active else "inactive_user"
        _fire_login_failed(username, ip, user_agent, reason=reason)
        raise AuthenticationException(_("Invalid username or password."), code="invalid_credentials")

    user.last_seen_at = timezone.now()
    user.save(update_fields=["last_seen_at"])
    login_succeeded.send(
        sender=User,
        username=username,
        user_id=user.pk,
        ip=ip,
        user_agent=user_agent,
        schema_name=current_schema(),
    )
    return user


def change_password(*, user: User, old_password: str, new_password: str) -> dict[str, str]:
    """Verify the old password, set the new one (ending every session), and
    return a fresh token pair so the current device stays logged in."""
    if not user.check_password(old_password):
        raise ValidationException(_("Current password is incorrect."), code="wrong_password")
    _validate_new_password(new_password, user)
    set_user_password(user, new_password)  # blacklists all refreshes + bumps tv
    user.refresh_from_db(fields=["token_version"])
    return issue_token_pair(user)


def _validate_new_password(raw: str, user: User) -> None:
    try:
        validate_password(raw, user=user)
    except DjangoValidationError as exc:
        raise ValidationException("; ".join(exc.messages), code="weak_password") from exc


def _fire_login_failed(username: str, ip: str, user_agent: str, *, reason: str) -> None:
    login_failed.send(
        sender=User,
        username=username,
        ip=ip,
        user_agent=user_agent,
        reason=reason,
        schema_name=current_schema(),
    )


# ---------------------------------------------------------------------------
# OTP machinery (password reset / contact verification — NOT login)
# ---------------------------------------------------------------------------


def _on_public_schema() -> bool:
    from django_tenants.utils import get_public_schema_name

    return current_schema() == get_public_schema_name()


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
    cooldown = _otp_cooldown_seconds()
    latest = (
        OTP.objects.filter(identifier=identifier)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if latest is None:
        return
    elapsed = (timezone.now() - latest).total_seconds()
    if elapsed < cooldown:
        raise ThrottledException(_("Please wait before requesting another code."), wait=cooldown - elapsed)


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
        raise ThrottledException(_("Too many requests from your network."))


@transaction.atomic
def send_otp(
    *,
    identifier: str,
    purpose: str,
    ip: str = "",
    user_agent: str = "",
) -> OTP:
    """Generate, store (hashed), and dispatch an OTP. Cooldown + per-IP capped.

    Callers must pass an explicit purpose (reset/verify) — there is no login
    purpose anymore."""

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
            subject="Starforge verification code",
            body=f"Your code is {code}. Valid for {settings.OTP_TTL_SECONDS // 60} minutes.",
        )

    schema = current_schema()
    transaction.on_commit(
        lambda: otp_requested.send(
            sender=OTP,
            identifier=identifier,
            purpose=purpose,
            ip=ip,
            user_agent=user_agent,
            schema_name=schema,
        )
    )
    return otp


def verify_otp(
    *,
    identifier: str,
    code: str,
    purpose: str,
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Verify an OTP and mark it consumed; raises on any failure.

    Failed attempts are persisted so the max-attempts cap actually bites, and
    ALL failure signals fire after the transaction commits (review fix: two of
    three failure paths previously fired inside a rolled-back transaction)."""

    identifier = _normalize(identifier)
    failure: tuple[str, type[StarforgeError], StrOrPromise] | None = None

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
            failure = (
                "no_active_code",
                ValidationException,
                _("Code expired or never issued. Request a new one."),
            )
        elif otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            failure = ("too_many_attempts", ThrottledException, _("Too many attempts. Request a new code."))
        else:
            otp.attempts += 1
            if check_password(code, otp.code_hash):
                otp.consumed_at = timezone.now()
                otp.save(update_fields=["attempts", "consumed_at"])
            else:
                otp.save(update_fields=["attempts"])
                failure = ("wrong_code", ValidationException, _("Invalid code."))

    if failure is not None:
        reason, exc_class, detail = failure
        _fire_failed(identifier, ip, user_agent, reason=reason)
        raise exc_class(detail)

    otp_verified.send(
        sender=OTP,
        identifier=identifier,
        purpose=purpose,
        ip=ip,
        user_agent=user_agent,
        schema_name=current_schema(),
    )


def request_password_reset(*, identifier: str, ip: str = "", user_agent: str = "") -> None:
    """Send a reset OTP if (and only if) an account matches the identifier.

    Unknown identifiers are silently accepted — no SMS is sent, no OTP row is
    created, and the response is indistinguishable (anti-enumeration). The
    per-IP distinct-identifier cap is enforced BEFORE the existence check so
    probing sweeps still get throttled."""
    identifier = _normalize(identifier)
    _enforce_ip_cap(ip, identifier)
    if _find_by_identifier(identifier) is None:
        return
    send_otp(identifier=identifier, purpose=OTP.PURPOSE_RESET, ip=ip, user_agent=user_agent)


def reset_password(
    *, identifier: str, code: str, new_password: str, ip: str = "", user_agent: str = ""
) -> None:
    """Complete a password reset: verify the OTP, set the password, end all
    sessions. The user logs in fresh with the new password afterwards."""
    identifier = _normalize(identifier)
    verify_otp(identifier=identifier, code=code, purpose=OTP.PURPOSE_RESET, ip=ip, user_agent=user_agent)
    user = _find_by_identifier(identifier)
    if user is None:  # unreachable in practice: no OTP is issued for unknowns
        raise ValidationException(_("Invalid code."))
    _validate_new_password(new_password, user)
    set_user_password(user, new_password)


def _find_by_identifier(identifier: str) -> User | None:
    lookup = {"email": identifier} if "@" in identifier else {"phone": identifier}
    return User.objects.filter(**lookup).first()


def _fire_failed(identifier: str, ip: str, user_agent: str, *, reason: str) -> None:
    otp_failed.send(
        sender=OTP,
        identifier=identifier,
        ip=ip,
        user_agent=user_agent,
        reason=reason,
        schema_name=current_schema(),
    )


# ---------------------------------------------------------------------------
# JWT pairs (TD-1 claims) and the tenant-bound refresh path
# ---------------------------------------------------------------------------


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
    claims). Tenant-bound (BLOCKER fix): a refresh minted on tenant A presented
    to tenant B is rejected before any user resolution — per-schema pk
    collisions would otherwise mint valid tokens for an unrelated user.
    Presenting an already-blacklisted token is treated as theft — every session
    for that user is revoked and 401 ``refresh_reused`` raised."""
    try:
        refresh = RefreshToken(raw_refresh)  # type: ignore[arg-type]
    except TokenError as exc:
        _detect_refresh_reuse(raw_refresh)  # raises refresh_reused if it is reuse
        raise AuthenticationException(
            _("Invalid or expired refresh token."), code="authentication_failed"
        ) from exc

    if refresh.get("schema") != current_schema():
        raise AuthenticationException(
            _("This token was issued for a different center."), code="tenant_mismatch"
        )

    user = User.objects.filter(pk=refresh.get("user_id")).first()
    if user is None:
        raise AuthenticationException(_("Invalid or expired refresh token."), code="authentication_failed")

    refresh.blacklist()
    return issue_token_pair(user)


def _detect_refresh_reuse(raw_refresh: str) -> None:
    """If `raw_refresh` is a syntactically valid token whose jti is already
    blacklisted, this *may* be a replay-theft — revoke all of that user's tokens.
    Only ever acts on tokens minted for THIS schema (cross-tenant tokens must not
    revoke a pk-colliding stranger's sessions).

    Crucially, theft is distinguished from legitimate invalidation by the `tv`
    claim: rotation blacklists a token WITHOUT bumping `tv` (so a replayed
    rotated token still carries the live `tv` = theft signal), whereas
    logout-everywhere / password-change / role-change blacklist tokens AND bump
    `tv`. A blacklisted token whose `tv` is already stale was killed by one of
    those — re-nuking would also kill the fresh pair the user just received, so
    we treat it as a plain expired token instead."""
    try:
        token = UntypedToken(raw_refresh)  # type: ignore[arg-type]  # signature + exp only
    except TokenError:
        return
    if token.get("schema") != current_schema():
        return
    jti = token.get("jti")
    user_id = token.get("user_id")
    if not jti or not user_id:
        return
    if not BlacklistedToken.objects.filter(token__jti=jti).exists():
        return
    user = User.objects.filter(pk=user_id).first()
    if user is None or token.get("tv") != user.token_version:
        return  # already invalidated by a tv bump — not theft
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
