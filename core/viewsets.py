"""Tenant-safe base ViewSet.

Every domain ViewSet should inherit `TenantSafeModelViewSet`, which wires the
default permissions and asserts that the active connection is on a tenant
schema (not the public schema). This guards against accidentally serving
tenant data through the public URLConf.
"""

from __future__ import annotations

from django.db import connection
from rest_framework import viewsets

from core.exceptions import TenantContextMissing
from core.permissions import ObjectScopedPermission, RolePermission


class TenantSafeModelViewSet(viewsets.ModelViewSet):
    permission_classes = [RolePermission, ObjectScopedPermission]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # django-tenants exposes schema_name on the connection. Public schema
        # routes should never reach a tenant-only view.
        schema = getattr(connection, "schema_name", None)
        if not schema or schema == getattr(connection, "get_public_schema_name", lambda: "public")():
            raise TenantContextMissing("This endpoint requires a tenant subdomain.")
