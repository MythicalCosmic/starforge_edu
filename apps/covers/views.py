from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.covers import services
from apps.covers.models import CoverRequest
from apps.covers.serializers import (
    AssignCoverSerializer,
    CoverRequestSerializer,
    CreateCoverSerializer,
)
from apps.teachers.models import TeacherProfile
from core.exceptions import PermissionException, ValidationException
from core.permissions import Role, get_role_memberships, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


class CoverRequestViewSet(TenantSafeModelViewSet):
    """Lesson cover requests (F18-1). A teacher (cover:write) requests cover for their
    own lesson; a manager (cover:approve) assigns a cover teacher or opens it to the
    branch pool; a teacher claims a pooled request. Approval reassigns the lesson."""

    serializer_class = CoverRequestSerializer
    resource = "cover"
    required_perms = {
        "list": "cover:read",
        "retrieve": "cover:read",
        "create": "cover:write",
        "claim": "cover:write",
        "cancel": "cover:write",
        "pool": "cover:read",
        "assign": "cover:approve",
        "open_pool": "cover:approve",
        "reject": "cover:approve",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("status", "pool", "branch", "lesson")
    ordering_fields = ("created_at",)

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def get_queryset(self):
        qs = CoverRequest.objects.select_related(
            "lesson", "requester", "cover_teacher", "branch", "decided_by"
        )
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        my = self._branch_ids()
        if has_permission_code(roles, "cover:approve"):
            return qs.filter(branch_id__in=my)  # managers see their branch's requests
        # a teacher sees: their own requests, claimable pool requests in their branch,
        # and requests assigned to them.
        return qs.filter(
            Q(requester=user)
            | (Q(pool=True, status=CoverRequest.Status.OPEN) & Q(branch_id__in=my))
            | Q(cover_teacher__user=user)
        )

    @extend_schema(request=CreateCoverSerializer, responses={201: CoverRequestSerializer}, tags=["cover"])
    def create(self, request, *args, **kwargs):
        ser = CreateCoverSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cover = services.create_cover_request(
            lesson=ser.validated_data["lesson"], requester=request.user, reason=ser.validated_data["reason"]
        )
        return Response(CoverRequestSerializer(cover).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=AssignCoverSerializer, responses={200: CoverRequestSerializer}, tags=["cover"])
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        ser = AssignCoverSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cover = services.assign_cover(
            cover_id=self.get_object().pk,
            cover_teacher=ser.validated_data["cover_teacher"],
            actor=request.user,
        )
        return Response(CoverRequestSerializer(cover).data)

    @extend_schema(request=None, responses={200: CoverRequestSerializer}, tags=["cover"])
    @action(detail=True, methods=["post"], url_path="open-pool")
    def open_pool(self, request, pk=None):
        cover = services.open_to_pool(cover_id=self.get_object().pk, actor=request.user)
        return Response(CoverRequestSerializer(cover).data)

    @extend_schema(request=None, responses={200: CoverRequestSerializer}, tags=["cover"])
    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if teacher is None:
            raise ValidationException(_("You are not a teacher."), code="not_a_teacher")
        cover = services.claim_cover(
            cover_id=self.get_object().pk, claimer_teacher=teacher, actor=request.user
        )
        return Response(CoverRequestSerializer(cover).data)

    @extend_schema(responses={200: CoverRequestSerializer(many=True)}, tags=["cover"])
    @action(detail=False, methods=["get"])
    def pool(self, request):
        """The claimable cover board (F18-2): open requests a manager has opened to the
        pool, scoped to the caller's branch(es) — what a teacher can claim right now."""
        qs = self.filter_queryset(self.get_queryset()).filter(
            pool=True, status=CoverRequest.Status.OPEN
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(CoverRequestSerializer(page, many=True).data)
        return Response(CoverRequestSerializer(qs, many=True).data)

    @extend_schema(request=None, responses={200: CoverRequestSerializer}, tags=["cover"])
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        cover = self.get_object()
        # Only the requester may withdraw their own request.
        if not request.user.is_superuser and cover.requester_id != request.user.id:
            raise PermissionException(_("You can only cancel your own request."), code="not_requester")
        cover = services.cancel_cover(cover_id=cover.pk, actor=request.user)
        return Response(CoverRequestSerializer(cover).data)

    @extend_schema(request=None, responses={200: CoverRequestSerializer}, tags=["cover"])
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        cover = services.reject_cover(cover_id=self.get_object().pk, actor=request.user)
        return Response(CoverRequestSerializer(cover).data)
