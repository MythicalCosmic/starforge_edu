"""Channels middleware: resolve tenant from hostname + authenticate via JWT.

Order: TenantResolver wraps the inner middleware so the User lookup runs
inside the tenant's schema (otherwise auth.User isn't there).
"""

from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django_tenants.utils import get_public_schema_name, get_tenant_model
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

User = get_user_model()


@database_sync_to_async
def _resolve_tenant_by_hostname(hostname: str):
    Tenant = get_tenant_model()
    try:
        return Tenant.objects.get(domains__domain=hostname)
    except Tenant.DoesNotExist:
        return None


@database_sync_to_async
def _user_from_token(raw_token: str):
    try:
        validated = UntypedToken(raw_token)  # type: ignore[arg-type]
    except (InvalidToken, TokenError):
        return AnonymousUser()
    try:
        return User.objects.get(pk=validated["user_id"])
    except User.DoesNotExist:
        return AnonymousUser()


class TenantAwareJWTAuthMiddleware(BaseMiddleware):
    """Resolves tenant by hostname; reads JWT from query string `token=` or
    Sec-WebSocket-Protocol header (`bearer.<token>`).
    """

    async def __call__(self, scope, receive, send):
        host = ""
        for header_name, value in scope.get("headers", []):
            if header_name == b"host":
                host = value.decode().split(":")[0]
                break

        tenant = await _resolve_tenant_by_hostname(host) if host else None
        if tenant is not None:
            connection.set_tenant(tenant)  # type: ignore[attr-defined]
        else:
            connection.set_schema_to_public()  # type: ignore[attr-defined]

        token = self._extract_token(scope)
        scope["user"] = await _user_from_token(token) if token else AnonymousUser()
        scope["tenant"] = tenant
        return await super().__call__(scope, receive, send)

    @staticmethod
    def _extract_token(scope) -> str | None:
        # 1) Sec-WebSocket-Protocol: bearer.<token>
        for header_name, value in scope.get("headers", []):
            if header_name == b"sec-websocket-protocol":
                for part in value.decode().split(","):
                    part = part.strip()
                    if part.startswith("bearer."):
                        return part.removeprefix("bearer.")
        # 2) ?token=<token>
        query = parse_qs(scope.get("query_string", b"").decode())
        token_list = query.get("token") or []
        return token_list[0] if token_list else None


def public_schema_name() -> str:
    return get_public_schema_name()
