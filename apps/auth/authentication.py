"""Tenant-bound JWT authentication.

Centers are isolated by Postgres schema, and user primary keys collide across
schemas. A bare JWT (looked up only by ``user_id``) would therefore authenticate
as a *different* user on the wrong tenant. We stamp the issuing schema into the
token (see ``apps.auth.services.issue_token_pair``) and refuse any token whose
``tenant_schema`` claim does not match the schema serving the request.
"""

from __future__ import annotations

from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

TENANT_CLAIM = "tenant_schema"


class TenantBoundJWTAuthentication(JWTAuthentication):
    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)
        current = getattr(connection, "schema_name", None)
        if token.get(TENANT_CLAIM) != current:
            raise InvalidToken("Token was not issued for this tenant.")
        return token
