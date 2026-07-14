"""Custom session authentication — no JWT library.

The opaque key returned by :func:`create_session` is the Bearer token. Only a
one-way SHA-256 digest is stored on ``Session``. A session row lives in the tenant
schema that created it, so a key only authenticates against that center (tenant
binding is automatic — no signed claim to forge or check cross-schema). Validation
is one indexed digest lookup (plus a temporary legacy-key fallback while old rows
are upgraded); revocation is a row update.
Roles are read LIVE per request by the permission layer, so a role change takes
effect immediately — there is no stale-token window and no token_version dance.

Used by BOTH view styles during the migration:
- ``SessionAuthentication`` (DRF auth class) — swapped into REST_FRAMEWORK so every
  existing DRF endpoint authenticates by session key.
- ``core.api_auth.require_auth`` — the same validation for plain function views.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import BaseAuthentication, get_authorization_header

_LAST_USED_STALE = timedelta(seconds=60)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_ROLE_MODEL_LABELS = {
    "student": "students.StudentProfile",
    "teacher": "teachers.TeacherProfile",
    "parent": "parents.ParentProfile",
    "staff": "org.StaffProfile",
}
_SESSION_HASH_PREFIX = "sha256$"
_MAX_SESSION_KEY_LENGTH = 256


def hash_session_key(key: str) -> str:
    """Return the non-reversible representation persisted for a Bearer key.

    Session keys contain 320 bits of CSPRNG entropy, so a fast digest is suitable:
    unlike a human password there is no feasible dictionary to brute-force. The
    prefix makes stored digests unambiguous and, critically, prevents a digest
    copied from the database from being accepted by the legacy plaintext fallback.
    """
    from core.utils import stable_hash

    return f"{_SESSION_HASH_PREFIX}{stable_hash(key)}"


def _looks_like_stored_session_hash(value: str) -> bool:
    digest = value.removeprefix(_SESSION_HASH_PREFIX)
    return (
        value.startswith(_SESSION_HASH_PREFIX)
        and len(digest) == 64
        and all(char in "0123456789abcdef" for char in digest)
    )


def _session_ttl() -> timedelta:
    return timedelta(days=int(getattr(settings, "SESSION_TTL_DAYS", 7)))


def create_session(
    user,
    *,
    ip: str = "",
    user_agent: str = "",
    device_id: str = "",
    read_only: bool = False,
    principal_kind: str = "",
    principal_id: int | None = None,
):
    """Issue a fresh session and return its row (``.key`` is available once).

    For role-native login, pass ``principal_kind`` (student/teacher/parent/staff) +
    ``principal_id`` (the role account's pk); ``user`` is still the account's linked User
    so all downstream authz/audit is unchanged. The raw key is attached only to
    this in-memory instance; database reads expose ``key_hash`` and never recover it.
    """
    from apps.users.models import Session

    raw_key = secrets.token_urlsafe(40)
    session = Session.objects.create(
        user=user,
        key_hash=hash_session_key(raw_key),
        principal_kind=(principal_kind or "")[:16],
        principal_id=principal_id,
        ip_address=(ip or "")[:64],
        user_agent=(user_agent or "")[:512],
        device_id=(device_id or "")[:128],
        read_only=read_only,
        expires_at=timezone.now() + _session_ttl(),
    )
    session._issued_key = raw_key
    return session


def validate_session_key(key: str):
    """Resolve a session key to its active session, or ``None``.

    Active = exists, not revoked, not expired, and the user is still active. Touches
    ``last_used_at`` at most once a minute (one cheap throttled UPDATE, no signals)."""
    from apps.users.models import Session

    if not key or len(key) > _MAX_SESSION_KEY_LENGTH:
        return None
    now = timezone.now()
    key_hash = hash_session_key(key)
    session = (
        Session.objects.select_related("user")
        .filter(key_hash=key_hash, revoked_at__isnull=True, expires_at__gt=now)
        .first()
    )
    # Safe dual-read during rollout: old rows may still contain their raw key.
    # Never run this branch for a value shaped like a stored digest, otherwise a
    # read-only database leak would itself become a usable Bearer credential.
    if session is None and not _looks_like_stored_session_hash(key):
        session = (
            Session.objects.select_related("user")
            .filter(key_hash=key, revoked_at__isnull=True, expires_at__gt=now)
            .first()
        )
        if session is not None:
            Session.objects.filter(pk=session.pk, key_hash=key).update(key_hash=key_hash)
            session.key_hash = key_hash
    if session is None or not session.user.is_active or not _has_live_role_principal(session):
        return None
    if (now - session.last_used_at) > _LAST_USED_STALE:
        Session.objects.filter(pk=session.pk).update(last_used_at=now)
    return session


def _has_live_role_principal(session) -> bool:
    """Validate the role identity represented by a role-native session.

    The linked ``User`` is only an authorization bridge.  It is insufficient proof that
    the student/teacher/parent/staff account still exists or remains active, and a bridge
    with Django-admin privileges must never be accepted on the role session surface.
    """
    kind = session.principal_kind
    principal_id = session.principal_id
    if not kind and principal_id is None:
        return True  # platform User login / read-only admin impersonation
    model_label = _ROLE_MODEL_LABELS.get(kind)
    if model_label is None or principal_id is None:
        return False

    from django.apps import apps as django_apps

    model = django_apps.get_model(model_label)
    account = model.objects.filter(pk=principal_id).only("is_active", "user_id").first()
    return bool(
        account is not None
        and account.is_active
        and account.user_id == session.user_id
        and not session.user.is_staff
        and not session.user.is_superuser
    )


def revoke_session(key: str) -> None:
    from apps.users.models import Session

    if not key or len(key) > _MAX_SESSION_KEY_LENGTH:
        return
    candidates = [hash_session_key(key)]
    if not _looks_like_stored_session_hash(key):
        candidates.append(key)  # legacy plaintext row during rollout
    Session.objects.filter(key_hash__in=candidates, revoked_at__isnull=True).update(revoked_at=timezone.now())


def revoke_all_for_user(user_id: int) -> int:
    """Revoke every active session for a user (logout-all / password change). Returns
    the number revoked."""
    from apps.users.models import Session

    return Session.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=timezone.now())


class SessionAuthentication(BaseAuthentication):
    """DRF authenticator: ``Authorization: Bearer <issued-key>`` -> (user, session).

    No header -> ``None`` (anonymous; ``IsAuthenticated`` then 401s). A Bearer key
    that is unknown/expired/revoked -> ``AuthenticationException`` (401)."""

    keyword = b"bearer"

    def authenticate(self, request):
        from core.exceptions import AuthenticationException

        header = get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword:
            return None
        if len(header) != 2:
            raise AuthenticationException(_("Invalid Authorization header."), code="authentication_failed")
        try:
            key = header[1].decode()
        except UnicodeError:
            raise AuthenticationException(
                _("Invalid Authorization header."), code="authentication_failed"
            ) from None
        session = validate_session_key(key)
        if session is None:
            raise AuthenticationException(
                _("Your session is invalid or has expired. Please sign in again."),
                code="authentication_failed",
            )
        if session.read_only and request.method not in _SAFE_METHODS:
            # Enforce read-only impersonation centrally at authentication time.  This
            # covers DRF and the layered plain-Django views because both call this same
            # authenticator; individual views no longer need to remember the guard.
            from core.exceptions import PermissionException

            raise PermissionException(code="read_only_token")
        request.is_read_only_token = session.read_only
        # Role-native identity the caller signed in as (blank for legacy sessions).
        request.principal_kind = session.principal_kind
        # Model signals fire after authentication but have no request argument;
        # publish the live principal to the request-local audit context.
        from apps.audit.context import bind_actor

        bind_actor(session.user)
        request.principal_id = session.principal_id
        return session.user, session

    def authenticate_header(self, request) -> str:
        return "Bearer"
