from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response

from apps.access.models import RolePermissionOverride
from apps.access.serializers import RolePermissionOverrideSerializer
from core.permissions import (
    ROLE_PERMISSION_MATRIX,
    Role,
    default_perms,
    role_effective_permissions,
)
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet


class RolePermissionOverrideViewSet(TenantSafeModelViewSet):
    """Manage this center's permission overrides (A-2). Gated at access:read/write,
    which only the director holds by default (*:*) — changing who-can-do-what is a
    high-trust action. A director may delegate it by granting access:write to another
    role via an override (everything except the master wildcard is grantable)."""

    serializer_class = RolePermissionOverrideSerializer
    resource = "access"
    required_perms = default_perms("access")
    queryset = RolePermissionOverride.objects.select_related("created_by").all()
    filterset_fields = ("role", "effect", "permission")
    ordering_fields = ("role", "permission", "created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class EffectiveRolesView(TenantSafeAPIView):
    """GET /api/v1/access/roles/ — every role with its EFFECTIVE permissions
    (static defaults with this center's overrides applied), as {granted, revoked}
    so a verb carved out of a resource-wildcard is visible. The admin UI's
    'what can each role do' screen."""

    resource = "access"
    required_perms = {"get": "access:read"}

    @extend_schema(
        summary="Effective permissions for every role (defaults + overrides)",
        responses={200: OpenApiResponse(description="{roles: {role: {granted, revoked}}}")},
        tags=["access"],
    )
    def get(self, request):
        # One override query, shared across all roles (memoized on the request).
        from core.permissions import _request_overrides

        overrides = _request_overrides(request)
        roles = {role: role_effective_permissions(role, overrides) for role in Role.ALL}
        return Response({"roles": roles})


class PermissionCatalogView(TenantSafeAPIView):
    """GET /api/v1/access/permissions/ — the catalog of known permission codes a
    center can grant/revoke (the union of everything the static matrix references)."""

    resource = "access"
    required_perms = {"get": "access:read"}

    @extend_schema(
        summary="Catalog of grantable permission codes",
        responses={200: OpenApiResponse(description="{permissions: [codes]}")},
        tags=["access"],
    )
    def get(self, request):
        codes: set[str] = set()
        for perms in ROLE_PERMISSION_MATRIX.values():
            codes |= perms
        return Response({"permissions": sorted(codes)})
