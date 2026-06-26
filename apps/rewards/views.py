from __future__ import annotations

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.rewards import services
from apps.rewards.models import RewardGrant, RewardType
from apps.rewards.serializers import (
    GrantRewardSerializer,
    RewardGrantSerializer,
    RewardTypeSerializer,
)
from core.permissions import _request_overrides, default_perms, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


class RewardTypeViewSet(TenantSafeModelViewSet):
    """The center's catalog of reward types (F17-1). Read at rewards:read, managed
    at rewards:write."""

    serializer_class = RewardTypeSerializer
    resource = "rewards"
    required_perms = default_perms("rewards")
    # No DELETE: a type may have grants (PROTECT) and is part of the audit history —
    # managers retire it with is_active=False instead.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    queryset = RewardType.objects.select_related("created_by").all()
    filterset_fields = ("is_cash", "is_active")
    search_fields = ("name",)
    ordering_fields = ("name", "created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class RewardGrantViewSet(TenantSafeModelViewSet):
    """Grants of rewards to staff (F17-1). A manager (rewards:write) grants + sees all;
    a staff member (rewards:read) sees the rewards they received via `mine`. A cash
    grant raises a `reward`-kind A-1 approval for the payout."""

    serializer_class = RewardGrantSerializer
    resource = "rewards"
    required_perms = {
        "list": "rewards:write",
        "retrieve": "rewards:read",
        "create": "rewards:write",
        "mine": "rewards:read",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("reward_type", "recipient")
    ordering_fields = ("granted_at",)

    def _base(self):
        return RewardGrant.objects.select_related(
            "reward_type", "recipient", "granted_by", "approval_request"
        )

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or has_permission_code(
            get_user_roles(self.request), "rewards:write", _request_overrides(self.request)
        ):
            return self._base()  # managers see every grant
        return self._base().filter(Q(recipient=user) | Q(granted_by=user))  # staff see their own

    @extend_schema(request=GrantRewardSerializer, responses={201: RewardGrantSerializer}, tags=["rewards"])
    def create(self, request, *args, **kwargs):
        ser = GrantRewardSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        grant = services.grant_reward(
            reward_type=ser.validated_data["reward_type"],
            recipient=ser.validated_data["recipient"],
            granted_by=request.user,
            amount_uzs=ser.validated_data.get("amount_uzs"),
            reason=ser.validated_data["reason"],
        )
        return Response(RewardGrantSerializer(grant).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: RewardGrantSerializer(many=True)}, tags=["rewards"])
    @action(detail=False, methods=["get"])
    def mine(self, request):
        qs = self._base().filter(recipient=request.user)
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(RewardGrantSerializer(page, many=True).data)
        return Response(RewardGrantSerializer(qs, many=True).data)
