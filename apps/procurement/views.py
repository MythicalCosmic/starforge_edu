from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.procurement import services
from apps.procurement.models import PurchaseOrder
from apps.procurement.serializers import (
    CreatePurchaseOrderSerializer,
    PurchaseOrderSerializer,
)
from core.exceptions import PermissionException
from core.permissions import Role, get_role_memberships, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


class PurchaseOrderViewSet(TenantSafeModelViewSet):
    """Procurement / purchase orders (#15) — the itemised surface over the A-1 engine.
    Raise a PO (line items → a procurement request totalling them); the approve and
    cashier-disburse decision lives in the unified approvals queue (/api/v1/approvals/)."""

    serializer_class = PurchaseOrderSerializer
    resource = "procurement"
    required_perms = {
        "list": "procurement:read",
        "retrieve": "procurement:read",
        "create": "procurement:write",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("branch", "request__status")
    ordering_fields = ("created_at",)

    def _assert_branch_in_scope(self, branch) -> None:
        """A requester may only book spend against a branch they belong to — a
        branch-A actor must not raise a PO (and its ledger row) against branch B.
        Director/superuser are unscoped. A centre-wide (no branch) PO is allowed."""
        if branch is None:
            return
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return
        my = {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}
        if branch.id not in my:
            raise PermissionException(
                _("You can only raise a purchase order for your own branch."),
                code="branch_out_of_scope",
            )

    def get_queryset(self):
        qs = PurchaseOrder.objects.select_related("request", "branch", "created_by").prefetch_related("items")
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        # Finance handlers (those who approve/disburse the money) see every PO; a
        # plain requester sees only the ones they raised (mirrors approvals scoping).
        if has_permission_code(roles, "approvals:approve") or has_permission_code(
            roles, "approvals:disburse"
        ):
            return qs
        return qs.filter(request__requested_by=user)  # type: ignore[misc]  # request.user is User|AnonymousUser

    @extend_schema(
        request=CreatePurchaseOrderSerializer, responses={201: PurchaseOrderSerializer}, tags=["procurement"]
    )
    def create(self, request, *args, **kwargs):
        ser = CreatePurchaseOrderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self._assert_branch_in_scope(ser.validated_data.get("branch"))
        po = services.create_purchase_order(
            requested_by=request.user,
            supplier=ser.validated_data["supplier"],
            title=ser.validated_data["title"],
            items=ser.validated_data["items"],
            description=ser.validated_data["description"],
            branch=ser.validated_data.get("branch"),
        )
        return Response(PurchaseOrderSerializer(po).data, status=status.HTTP_201_CREATED)
