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

from core.exceptions import PermissionException, TenantContextMissing
from core.permissions import ObjectScopedPermission, Role, RolePermission, get_role_memberships


def assert_tenant_context() -> None:
    schema = getattr(connection, "schema_name", None)
    if not schema or schema == get_public_schema_name():
        raise TenantContextMissing()


class TenantSafeModelViewSet(viewsets.ModelViewSet):
    permission_classes = [RolePermission, ObjectScopedPermission]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        assert_tenant_context()

    def perform_create(self, serializer):
        # ObjectScopedPermission only runs via has_object_permission (detail
        # routes) — create has no object yet, so a branch/department-scoped role
        # could otherwise create rows in ANY branch. Enforce the same scope on
        # the incoming branch/department here.
        self._assert_create_scope(serializer)
        serializer.save()

    def _assert_create_scope(self, serializer) -> None:
        scope = getattr(self, "object_scope", None)
        if not scope:
            return
        user = self.request.user
        if getattr(user, "is_superuser", False):
            return
        memberships = get_role_memberships(self.request)
        if any(m.role == Role.DIRECTOR for m in memberships):
            return
        target = serializer.validated_data.get(scope)
        if target is None:
            return
        target_id = getattr(target, "pk", target)
        allowed = {getattr(m, f"{scope}_id") for m in memberships}
        if target_id not in allowed:
            raise PermissionException(code="out_of_scope")


class TenantSafeAPIView(APIView):
    # Fail closed by default (TD-4): a subclass that forgets to declare
    # permission_classes must NOT inherit DRF's permissive IsAuthenticated.
    # Self-scoped views (e.g. the iCal feed) override this explicitly.
    permission_classes = [RolePermission]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        assert_tenant_context()
