"""Channels middleware: resolve tenant from hostname + authenticate via JWT.

TD-1 for websockets: the token must be an *access* token, its ``schema`` claim
must match the host-resolved tenant, and its ``tv`` claim must equal the
user's current ``token_version`` (and the user must be active). Any failure
yields ``AnonymousUser`` — consumers (e.g. ``PingConsumer``) close 4401.

Schema handling: the user lookup runs via ``database_sync_to_async`` on
asgiref's thread-sensitive executor thread, whose thread-local DB connection
is independent of the event loop's. The schema switch therefore happens
*inside* ``_user_from_token`` via ``schema_context`` — setting the tenant on
the event-loop thread would never reach the thread that runs the query.

NOTE for Day-4 consumers: ``scope["tenant"]`` is plain scope state, it does
NOT set the connection schema. Any consumer doing DB work must wrap it in
``schema_context(scope["tenant"].schema_name)`` itself.
"""

from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()


@database_sync_to_async
def _resolve_tenant_by_hostname(hostname: str):
    Tenant = get_tenant_model()
    try:
        return Tenant.objects.get(domains__domain=hostname)
    except Tenant.DoesNotExist:
        return None


@database_sync_to_async
def _user_from_token(raw_token: str, tenant):
    try:
        # AccessToken enforces token_type == "access" — a refresh token must
        # not authenticate a socket.
        validated = AccessToken(raw_token)  # type: ignore[arg-type]
    except (InvalidToken, TokenError):
        return AnonymousUser()

    expected_schema = tenant.schema_name if tenant is not None else get_public_schema_name()
    if validated.get("schema") != expected_schema:
        # TD-1: the token is bound to the tenant that minted it; a tenant-A
        # token presented on tenant B's host is a cross-tenant replay.
        return AnonymousUser()

    # Switch schema on THIS thread — database_sync_to_async runs on asgiref's
    # thread-sensitive executor whose connection the event loop never touched.
    with schema_context(expected_schema):
        try:
            user = User.objects.get(pk=validated["user_id"])
        except User.DoesNotExist:
            return AnonymousUser()
        if not user.is_active or validated.get("tv") != getattr(user, "token_version", None):
            # Logout-everywhere / role-change invalidation (TD-1 `tv` claim).
            return AnonymousUser()
        return user


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

        token = self._extract_token(scope)
        scope["user"] = await _user_from_token(token, tenant) if token else AnonymousUser()
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
