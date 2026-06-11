"""Tenant-safe base views.

Every tenant-scoped view must assert the active connection is on a tenant
schema (not public). `TenantSafeModelViewSet` covers CRUD; `TenantSafeAPIView`
covers non-CRUD APIViews (settings endpoint, custom actions). This guards
against accidentally serving tenant data through the public URLConf.
"""

from __future__ import annotations

from django.db import connection
from django_tenants.utils import get_public_schema_name
from rest_framework import viewsets
from rest_framework.views import APIView

from core.exceptions import TenantContextMissing
from core.permissions import ObjectScopedPermission, RolePermission


def assert_tenant_context() -> None:
    schema = getattr(connection, "schema_name", None)
    if not schema or schema == get_public_schema_name():
        raise TenantContextMissing()


class TenantSafeModelViewSet(viewsets.ModelViewSet):
    permission_classes = [RolePermission, ObjectScopedPermission]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        assert_tenant_context()


class TenantSafeAPIView(APIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        assert_tenant_context()
