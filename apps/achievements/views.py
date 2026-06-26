from __future__ import annotations

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.achievements import services
from apps.achievements.models import Achievement, AchievementGrant
from apps.achievements.serializers import (
    AchievementCreateSerializer,
    AchievementGrantSerializer,
    AchievementSerializer,
    GrantSerializer,
)
from apps.students.models import StudentProfile
from apps.students.selectors import student_profile_for
from core.permissions import Role, get_role_memberships, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


class AchievementViewSet(TenantSafeModelViewSet):
    """Custom achievements (F15-2). Staff with achievements:write create + grant;
    a teacher-requested GLOBAL achievement is pending until a manager
    (achievements:approve) approves it. Students see active achievements + their own
    granted wall (`mine`)."""

    serializer_class = AchievementSerializer
    resource = "achievements"
    required_perms = {
        "list": "achievements:read",
        "retrieve": "achievements:read",
        "create": "achievements:write",
        "grant": "achievements:write",
        "approve": "achievements:approve",
        "reject": "achievements:approve",
        "mine": "achievements:read",
        # Staff-only: who earned an achievement (+ the staff notes) is NOT for a
        # student/parent to enumerate — they only get their own wall via `mine`.
        "grants": "achievements:write",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("scope", "status", "cohort", "branch")
    ordering_fields = ("created_at", "name")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def _is_director(self) -> bool:
        return self.request.user.is_superuser or Role.DIRECTOR in get_user_roles(self.request)

    def get_queryset(self):
        qs = Achievement.objects.select_related("cohort", "branch", "created_by")
        if self._is_director():
            return qs  # the director manages the whole center
        roles = get_user_roles(self.request)
        if has_permission_code(roles, "achievements:write"):
            # Staff manage their own branch's achievements + active center-wide globals,
            # plus anything they created (so a teacher sees their own pending request).
            return qs.filter(
                Q(created_by=self.request.user)
                | Q(branch_id__in=self._branch_ids())
                | (Q(branch__isnull=True) & Q(status=Achievement.Status.ACTIVE))
            )
        return qs.filter(status=Achievement.Status.ACTIVE)  # students/parents: the live catalog

    @extend_schema(
        request=AchievementCreateSerializer, responses={201: AchievementSerializer}, tags=["achievements"]
    )
    def create(self, request, *args, **kwargs):
        ser = AchievementCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        roles = get_user_roles(request)
        can_approve = request.user.is_superuser or has_permission_code(roles, "achievements:approve")
        achievement = services.create_achievement(
            creator=request.user,
            can_approve=can_approve,
            is_scoped=not self._is_director(),
            creator_branch_ids=self._branch_ids(),
            **ser.validated_data,
        )
        return Response(AchievementSerializer(achievement).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: AchievementSerializer}, tags=["achievements"])
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        achievement = services.decide_achievement(
            achievement_id=self.get_object().pk, approve=True, actor=request.user
        )
        return Response(AchievementSerializer(achievement).data)

    @extend_schema(request=None, responses={200: AchievementSerializer}, tags=["achievements"])
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        achievement = services.decide_achievement(
            achievement_id=self.get_object().pk, approve=False, actor=request.user
        )
        return Response(AchievementSerializer(achievement).data)

    @extend_schema(
        request=GrantSerializer, responses={201: AchievementGrantSerializer}, tags=["achievements"]
    )
    @action(detail=True, methods=["post"])
    def grant(self, request, pk=None):
        ser = GrantSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        grant = services.grant_achievement(
            achievement=self.get_object(),
            student=ser.validated_data["student"],
            granted_by=request.user,
            note=ser.validated_data["note"],
        )
        return Response(AchievementGrantSerializer(grant).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="The signed-in student's granted achievements (their wall)",
        responses={200: AchievementGrantSerializer(many=True)},
        tags=["achievements"],
    )
    @action(detail=False, methods=["get"])
    def mine(self, request):
        # A student sees their own wall; a parent sees their guardian-linked children's.
        student = student_profile_for(request.user)
        if student is not None:
            student_ids = [student.pk]
        else:
            student_ids = list(
                StudentProfile.objects.filter(guardians__parent__user=request.user).values_list(
                    "pk", flat=True
                )
            )
        qs = (
            AchievementGrant.objects.filter(student_id__in=student_ids)
            .select_related("achievement", "granted_by")
            .order_by("-granted_at")
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(AchievementGrantSerializer(page, many=True).data)
        return Response(AchievementGrantSerializer(qs, many=True).data)

    @extend_schema(
        summary="Grants of one achievement",
        responses={200: AchievementGrantSerializer(many=True)},
        tags=["achievements"],
    )
    @action(detail=True, methods=["get"])
    def grants(self, request, pk=None):
        qs = self.get_object().grants.select_related("student", "granted_by")
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(AchievementGrantSerializer(page, many=True).data)
        return Response(AchievementGrantSerializer(qs, many=True).data)
