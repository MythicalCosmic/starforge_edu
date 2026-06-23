from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.approvals import selectors, services
from apps.approvals.models import LedgerEntry
from apps.approvals.serializers import (
    ApprovalDecisionSerializer,
    ApprovalDisburseSerializer,
    ApprovalRequestCreateSerializer,
    ApprovalRequestSerializer,
    LedgerEntrySerializer,
)
from core.exceptions import PermissionException
from core.permissions import RolePermission, get_user_roles
from core.viewsets import TenantSafeModelViewSet, assert_tenant_context


class ApprovalRequestViewSet(TenantSafeModelViewSet):
    """The Approvals engine (A-1). Anyone with approvals:write may request; approvers
    (approvals:approve) decide; cashiers (approvals:disburse) pay out -> ledger row.
    A requester sees only their own; handlers see all (selectors.scoped_requests)."""

    serializer_class = ApprovalRequestSerializer
    resource = "approvals"
    required_perms = {
        "list": "approvals:read",
        "retrieve": "approvals:read",
        "create": "approvals:write",
        "approve": "approvals:approve",
        "reject": "approvals:approve",
        "cancel": "approvals:write",
        "disburse": "approvals:disburse",
    }
    filterset_fields = ("kind", "status", "branch")
    ordering_fields = ("created_at", "amount_uzs")
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return selectors.scoped_requests(user=self.request.user, roles=get_user_roles(self.request))

    @extend_schema(
        request=ApprovalRequestCreateSerializer, responses={201: ApprovalRequestSerializer}, tags=["approvals"]
    )
    def create(self, request, *args, **kwargs):
        ser = ApprovalRequestCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        req = services.create_request(requested_by=request.user, **ser.validated_data)
        return Response(ApprovalRequestSerializer(req).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=ApprovalDecisionSerializer, responses={200: ApprovalRequestSerializer}, tags=["approvals"])
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        req = self.get_object()
        ser = ApprovalDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        req = services.approve(request_id=req.pk, actor=request.user, note=ser.validated_data["note"])
        return Response(ApprovalRequestSerializer(req).data)

    @extend_schema(request=ApprovalDecisionSerializer, responses={200: ApprovalRequestSerializer}, tags=["approvals"])
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req = self.get_object()
        ser = ApprovalDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        req = services.reject(request_id=req.pk, actor=request.user, note=ser.validated_data["note"])
        return Response(ApprovalRequestSerializer(req).data)

    @extend_schema(request=None, responses={200: ApprovalRequestSerializer}, tags=["approvals"])
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        # Only the requester may cancel their own request (approvals:write is broad).
        if not request.user.is_superuser and req.requested_by_id != request.user.id:
            raise PermissionException(_("You can only cancel your own request."), code="not_requester")
        req = services.cancel(request_id=req.pk, actor=request.user)
        return Response(ApprovalRequestSerializer(req).data)

    @extend_schema(request=ApprovalDisburseSerializer, responses={200: ApprovalRequestSerializer}, tags=["approvals"])
    @action(detail=True, methods=["post"])
    def disburse(self, request, pk=None):
        req = self.get_object()
        ser = ApprovalDisburseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        req = services.disburse(
            request_id=req.pk,
            payment_method_id=ser.validated_data["payment_method"],
            actor=request.user,
            direction=ser.validated_data["direction"],
            entry_type=ser.validated_data["entry_type"],
            party_label=ser.validated_data["party_label"],
        )
        return Response(ApprovalRequestSerializer(req).data)


class LedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only money-movement ledger. Entries are written only by services
    (append-only) — there is no create/update/delete API."""

    serializer_class = LedgerEntrySerializer
    permission_classes = [RolePermission]
    resource = "ledger"
    required_perms = {"list": "ledger:read", "retrieve": "ledger:read"}
    queryset = LedgerEntry.objects.select_related("branch", "payment_method", "created_by").all()
    filterset_fields = ("direction", "entry_type", "branch", "source_kind")
    ordering_fields = ("created_at", "amount_uzs")

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        assert_tenant_context()

    @extend_schema(responses={200: LedgerEntrySerializer(many=True)}, tags=["ledger"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
