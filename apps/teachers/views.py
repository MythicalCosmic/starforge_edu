from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.teachers import selectors, services
from apps.teachers.serializers import (
    TeacherCreateSerializer,
    TeacherReadSerializer,
    TeacherUpdateSerializer,
)
from core.viewsets import TenantSafeModelViewSet


class TeacherViewSet(TenantSafeModelViewSet):
    resource = "teachers"
    object_scope = "branch"
    filterset_fields = ("branch", "department", "is_substitute")
    search_fields = ("user__first_name", "user__last_name", "user__phone")
    ordering_fields = ("created_at", "hire_date")

    def get_queryset(self):
        return selectors.list_teachers()

    def get_serializer_class(self):
        if self.action == "create":
            return TeacherCreateSerializer
        if self.action in ("update", "partial_update"):
            return TeacherUpdateSerializer
        return TeacherReadSerializer

    @extend_schema(
        summary="Create a teacher (creates user + profile)",
        request=TeacherCreateSerializer,
        responses={201: TeacherReadSerializer},
        tags=["teachers"],
    )
    def create(self, request, *args, **kwargs):
        serializer = TeacherCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        teacher = services.create_teacher(**serializer.validated_data)
        return Response(TeacherReadSerializer(teacher).data, status=status.HTTP_201_CREATED)
