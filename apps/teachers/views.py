from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.teachers import selectors, services
from apps.teachers.serializers import (
    TeacherCreateSerializer,
    TeacherReadSerializer,
    TeacherUpdateSerializer,
)
from core.exceptions import NotFoundException
from core.permissions import get_user_roles
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet


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


class TeacherDashboardView(TenantSafeAPIView):
    """GET /api/v1/teachers/dashboard/ — the signed-in teacher's own cockpit
    (groups, students, level groups, next lessons + type, upcoming exams, expected
    graduations, outstanding rule acknowledgments). Any authenticated user with a
    teacher profile; 404 not_a_teacher otherwise."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="The signed-in teacher's dashboard",
        responses={200: OpenApiResponse(description="dashboard object"), 404: OpenApiResponse()},
        tags=["teachers"],
    )
    def get(self, request):
        teacher = selectors.teacher_profile_for(request.user)
        if teacher is None:
            raise NotFoundException(_("You do not have a teacher profile."), code="not_a_teacher")
        return Response(
            selectors.teacher_dashboard(teacher=teacher, user=request.user, roles=get_user_roles(request))
        )
