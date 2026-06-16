"""drf-spectacular extensions.

Registering an `OpenApiAuthenticationExtension` for the custom
`TenantAwareJWTAuthentication` (TD-1) teaches the schema generator to emit a
`bearer`/JWT security scheme instead of warning "could not resolve authenticator"
on every view. Importing this module is enough to register it (drf-spectacular
auto-registers extension subclasses on definition); `config.urls` imports it.
"""

from __future__ import annotations

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class TenantAwareJWTScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.TenantAwareJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
