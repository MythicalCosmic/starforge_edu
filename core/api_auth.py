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


def require_perm(*codes: str) -> Callable[[ViewFunc], ViewFunc]:
    """Require the caller hold AT LEAST ONE of ``codes`` in the role matrix.

    Must wrap a ``@require_auth`` view (it reads ``request``'s resolved roles). A
    superuser/DIRECTOR (``*:*``) passes any check via ``has_permission_code``."""

    def decorator(view_func: ViewFunc) -> ViewFunc:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            from core.exceptions import PermissionException
            from core.permissions import get_user_roles, has_permission_code

            roles = get_user_roles(request)  # type: ignore[arg-type]
            if not any(has_permission_code(roles, code) for code in codes):
                raise PermissionException(
                    "You do not have permission to perform this action.", code="forbidden"
                )
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
