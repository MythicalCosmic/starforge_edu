"""Auth/permission decorators for the layered (plain-Django) view style.

Function-based views in the new architecture authenticate with these decorators
instead of DRF's permission machinery. They REUSE the custom session authenticator
and the role-permission matrix, so a migrated endpoint enforces the exact same
security as the DRF stack (session validation + tenant binding + the matrix).

    @require_auth
    @require_perm("students:write")
    def create_student_view(request): ...
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse

from core.session_auth import SessionAuthentication

_authenticator = SessionAuthentication()

ViewFunc = Callable[..., HttpResponse]


def require_auth(view_func: ViewFunc) -> ViewFunc:
    """Authenticate the JWT and attach ``request.user``/``request.auth``.

    Raises ``AuthenticationException`` (-> JSON 401) when no/invalid credentials are
    presented; tenant-mismatch and stale-token are raised by the authenticator with
    their own codes. The domain error is rendered as JSON by core.middleware."""

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        from core.exceptions import AuthenticationException

        result = _authenticator.authenticate(request)
        if result is None:
            raise AuthenticationException(
                "Authentication credentials were not provided.", code="authentication_failed"
            )
        request.user, request.auth = result  # type: ignore[attr-defined]
        return view_func(request, *args, **kwargs)

    return wrapper


_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def require_perm(*codes: str) -> Callable[[ViewFunc], ViewFunc]:
    """Require the caller hold AT LEAST ONE of ``codes`` in the role matrix.

    Faithfully mirrors the DRF ``RolePermission`` + ``DenyWriteForReadOnlyToken`` so a
    migrated endpoint enforces identical authz: superuser bypass, the per-center A-2
    permission overrides, DIRECTOR (``*:*``) via ``has_permission_code``, and a 403
    ``read_only_token`` for any write under a read-only impersonation session. Wraps a
    ``@require_auth`` view (it reads ``request.user`` / resolved roles)."""

    def decorator(view_func: ViewFunc) -> ViewFunc:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            from core.exceptions import PermissionException
            from core.permissions import (
                _request_overrides,
                get_user_roles,
                has_permission_code,
                is_read_only_token,
            )

            # The permission helpers are duck-typed on .user/.method; a plain
            # HttpRequest satisfies them at runtime (typed as Request upstream).
            req: Any = request
            if request.method not in _SAFE_METHODS and is_read_only_token(req):
                raise PermissionException(code="read_only_token")
            if getattr(req.user, "is_superuser", False):
                return view_func(request, *args, **kwargs)
            roles = get_user_roles(req)
            overrides = _request_overrides(req)
            if not any(has_permission_code(roles, code, overrides) for code in codes):
                raise PermissionException(
                    "You do not have permission to perform this action.", code="forbidden"
                )
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
