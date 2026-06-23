from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.compliance import selectors, services
from apps.compliance.models import Rule
from apps.compliance.serializers import RuleSerializer
from core.exceptions import PermissionException
from core.permissions import default_perms, get_user_roles
from core.viewsets import TenantSafeModelViewSet

_SELF_ACTIONS = {"mine", "pending", "acknowledge"}


class RuleViewSet(TenantSafeModelViewSet):
    """Rule book. Managers (compliance:write) author rules; ANY authenticated user
    reads + acknowledges the rules that apply to them (mine/pending/acknowledge)."""

    queryset = Rule.objects.all()
    serializer_class = RuleSerializer
    resource = "compliance"
    required_perms = dict(default_perms("compliance"))
    filterset_fields = ("is_active",)
    search_fields = ("title",)
    ordering_fields = ("title",)

    def get_permissions(self):
        if getattr(self, "action", None) in _SELF_ACTIONS:
            return [IsAuthenticated()]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def update(self, request, *args, **kwargs):
        # Route body edits through the service so the version bumps (forcing
        # re-acknowledgment) only when the body actually changes.
        partial = kwargs.pop("partial", False)
        rule = self.get_object()
        ser = RuleSerializer(rule, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        updated = services.update_rule_body(rule=rule, **ser.validated_data)
        return Response(RuleSerializer(updated).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(
        summary="Rules that apply to me, each with my acknowledgment status",
        responses={200: OpenApiResponse(description="[{...rule, acknowledged: bool}]")},
        tags=["compliance"],
    )
    @action(detail=False, methods=["get"])
    def mine(self, request):
        roles = get_user_roles(request)
        rules = selectors.rules_for_roles(roles)
        acked = selectors.acknowledged_rule_ids_current(request.user, rules)
        data = [{**RuleSerializer(r).data, "acknowledged": r.id in acked} for r in rules]
        return Response(data)

    @extend_schema(
        summary="Rules I must still read and accept",
        responses={200: RuleSerializer(many=True)},
        tags=["compliance"],
    )
    @action(detail=False, methods=["get"])
    def pending(self, request):
        roles = get_user_roles(request)
        return Response(RuleSerializer(selectors.pending_rules(request.user, roles), many=True).data)

    @extend_schema(
        summary="Accept (acknowledge) a rule's current version",
        request=None,
        responses={200: OpenApiResponse(description="{acknowledged: true, version: int}")},
        tags=["compliance"],
    )
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        rule = get_object_or_404(Rule.objects.filter(is_active=True), pk=pk)
        roles = set(get_user_roles(request))
        targets = rule.applies_to_roles or []
        if targets and not request.user.is_superuser and not (set(targets) & roles):
            raise PermissionException(_("This rule does not apply to you."), code="rule_not_applicable")
        ack = services.acknowledge(rule=rule, user=request.user)
        return Response({"acknowledged": True, "version": ack.version})
