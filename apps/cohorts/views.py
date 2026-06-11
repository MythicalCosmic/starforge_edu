from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.cohorts import selectors, services
from apps.cohorts.serializers import (
    CohortMembershipSerializer,
    CohortReadSerializer,
    CohortWriteSerializer,
    EnrollSerializer,
    MoveStudentSerializer,
)
from core.exceptions import ValidationException
from core.permissions import default_perms
from core.viewsets import TenantSafeModelViewSet


class CohortViewSet(TenantSafeModelViewSet):
    resource = "cohorts"
    object_scope = "branch"
    required_perms = {
        **default_perms("cohorts"),
        "enroll": "cohorts:write",
        "move_student": "cohorts:write",
        "members": "cohorts:read",
    }
    filterset_fields = ("branch", "department", "is_archived")
    search_fields = ("name", "level")
    ordering_fields = ("start_date", "created_at", "name")

    def get_queryset(self):
        return selectors.list_cohorts()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return CohortWriteSerializer
        return CohortReadSerializer

    def update(self, request, *args, **kwargs):
        if self.get_object().is_archived:
            raise ValidationException(_("Cohort is archived."), code="cohort_archived")
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Enroll a student into this cohort",
        request=EnrollSerializer,
        responses={201: CohortMembershipSerializer},
        tags=["cohorts"],
    )
    @action(detail=True, methods=["post"])
    def enroll(self, request, pk=None):
        cohort = self.get_object()
        serializer = EnrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.enroll_student_in_cohort(
            cohort=cohort,
            student=serializer.validated_data["student"],
            start_date=serializer.validated_data.get("start_date"),
        )
        return Response(CohortMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Move a student into this cohort (history preserved)",
        request=MoveStudentSerializer,
        responses={200: OpenApiResponse(description="{membership, over_capacity}")},
        tags=["cohorts"],
    )
    @action(detail=True, methods=["post"], url_path="move-student")
    def move_student(self, request, pk=None):
        cohort = self.get_object()
        serializer = MoveStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.move_student(
            student=serializer.validated_data["student"],
            to_cohort=cohort,
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(
            {
                "membership": CohortMembershipSerializer(result["membership"]).data,
                "over_capacity": result["over_capacity"],
            }
        )

    @extend_schema(
        summary="Active members of this cohort",
        responses=CohortMembershipSerializer(many=True),
        tags=["cohorts"],
    )
    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        cohort = self.get_object()
        members = selectors.cohort_members(cohort=cohort)
        return Response(CohortMembershipSerializer(members, many=True).data)
