from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.compliance import selectors, services
from apps.compliance.models import Penalty, Rule
from apps.compliance.serializers import (
    IssuePenaltySerializer,
    PenaltySerializer,
    RuleSerializer,
    WaivePenaltySerializer,
)
from core.exceptions import PermissionException
from core.permissions import Role, default_perms, get_role_memberships, get_user_roles, has_permission_code
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


class PenaltyViewSet(TenantSafeModelViewSet):
    """Student demerits (F24-1). A teacher/manager (penalty:write) issues a penalty for
    a rule breach; a manager (penalty:waive) can reverse it (separate perm = SoD). The
    student (and their guardians) read their OWN record; staff read their branch's."""

    serializer_class = PenaltySerializer
    resource = "penalty"
    required_perms = {
        "list": "penalty:read",
        "retrieve": "penalty:read",
        "create": "penalty:write",
        "waive": "penalty:waive",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("status", "student", "branch")
    ordering_fields = ("issued_at", "points")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def get_queryset(self):
        qs = Penalty.objects.select_related(
            "rule", "student", "student__user", "branch", "issued_by", "waived_by"
        )
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        # Staff who issue or waive see their branch's penalties.
        if has_permission_code(roles, "penalty:write") or has_permission_code(roles, "penalty:waive"):
            return qs.filter(branch_id__in=self._branch_ids())
        # Everyone else sees only their own record (student) / their children's (parent).
        return qs.filter(Q(student__user=user) | Q(student__guardians__parent__user=user)).distinct()

    def _assert_student_in_scope(self, student) -> None:
        user = self.request.user
        if user.is_superuser or Role.DIRECTOR in get_user_roles(self.request):
            return
        if student.branch_id not in self._branch_ids():
            raise PermissionException(
                _("You can only penalise a student in your own branch."), code="branch_out_of_scope"
            )

    @extend_schema(request=IssuePenaltySerializer, responses={201: PenaltySerializer}, tags=["compliance"])
    def create(self, request, *args, **kwargs):
        ser = IssuePenaltySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        student = ser.validated_data["student"]
        self._assert_student_in_scope(student)
        penalty = services.issue_penalty(
            student=student,
            points=ser.validated_data["points"],
            reason=ser.validated_data["reason"],
            issued_by=request.user,
            rule=ser.validated_data.get("rule"),
        )
        return Response(PenaltySerializer(penalty).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=WaivePenaltySerializer, responses={200: PenaltySerializer}, tags=["compliance"])
    @action(detail=True, methods=["post"])
    def waive(self, request, pk=None):
        ser = WaivePenaltySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        penalty = services.waive_penalty(
            penalty_id=self.get_object().pk, actor=request.user, reason=ser.validated_data["reason"]
        )
        return Response(PenaltySerializer(penalty).data)
