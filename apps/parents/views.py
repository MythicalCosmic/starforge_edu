from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.parents import selectors, services
from apps.parents.serializers import (
    GuardianReadSerializer,
    GuardianWriteSerializer,
    ParentCreateSerializer,
    ParentReadSerializer,
    ParentUpdateSerializer,
    PickupAuthorizationSerializer,
)
from apps.students.selectors import student_report
from apps.students.serializers import StudentReadSerializer
from core.exceptions import NotFoundException
from core.permissions import default_perms, get_user_roles
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet


class ParentViewSet(TenantSafeModelViewSet):
    resource = "parents"
    required_perms = {**default_perms("parents"), "students": "parents:read"}
    search_fields = ("user__first_name", "user__last_name", "user__phone")
    ordering_fields = ("created_at",)

    def get_queryset(self):
        return selectors.scoped_parents(user=self.request.user, roles=get_user_roles(self.request))

    def get_serializer_class(self):
        if self.action == "create":
            return ParentCreateSerializer
        if self.action in ("update", "partial_update"):
            return ParentUpdateSerializer
        return ParentReadSerializer

    @extend_schema(
        summary="Create a parent (creates user + profile)",
        request=ParentCreateSerializer,
        responses={201: ParentReadSerializer},
        tags=["parents"],
    )
    def create(self, request, *args, **kwargs):
        serializer = ParentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent = services.create_parent(**serializer.validated_data)
        return Response(ParentReadSerializer(parent).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="A parent's linked students (siblings)",
        responses=StudentReadSerializer(many=True),
        tags=["parents"],
    )
    @action(detail=True, methods=["get"])
    def students(self, request, pk=None):
        parent = self.get_object()
        students = selectors.students_for_parent(parent=parent)
        return Response(StudentReadSerializer(students, many=True).data)


class GuardianViewSet(TenantSafeModelViewSet):
    """Parent↔student links. Updates are delete+recreate (no PUT/PATCH)."""

    resource = "parents"
    serializer_class = GuardianReadSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    filterset_fields = ("parent", "student", "is_primary")
    ordering_fields = ("id",)

    def get_queryset(self):
        return selectors.scoped_guardians(user=self.request.user, roles=get_user_roles(self.request))

    def get_serializer_class(self):
        if self.action == "create":
            return GuardianWriteSerializer
        return GuardianReadSerializer

    @extend_schema(
        summary="Link a parent to a student",
        request=GuardianWriteSerializer,
        responses={201: GuardianReadSerializer},
        tags=["parents"],
    )
    def create(self, request, *args, **kwargs):
        serializer = GuardianWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        guardian = services.link_guardian(**serializer.validated_data)
        return Response(GuardianReadSerializer(guardian).data, status=status.HTTP_201_CREATED)


class PickupAuthorizationViewSet(TenantSafeModelViewSet):
    resource = "parents"
    serializer_class = PickupAuthorizationSerializer
    filterset_fields = ("student", "is_active")
    ordering_fields = ("created_at",)

    def get_queryset(self):
        return selectors.scoped_pickups(user=self.request.user, roles=get_user_roles(self.request))


def _require_parent(request):
    parent = selectors.parent_profile_for(request.user)
    if parent is None:
        raise NotFoundException(_("You do not have a parent profile."), code="not_a_parent")
    return parent


class ParentChildrenView(TenantSafeAPIView):
    """GET /api/v1/parents/me/children/ — the signed-in parent's own linked children
    (self-service; no parents:read grant needed — it returns only this parent's rows)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="The signed-in parent's linked children",
        responses=StudentReadSerializer(many=True),
        tags=["parents"],
    )
    def get(self, request):
        parent = _require_parent(request)
        children = selectors.students_for_parent(parent=parent)
        return Response(StudentReadSerializer(children, many=True).data)


class ParentChildReportView(TenantSafeAPIView):
    """GET /api/v1/parents/me/children/{student_id}/report/ — a parent sees ONE of their
    children's report (per-lesson attendance, bill paid-status, and the child's own
    classroom rank — never a leaderboard). 404 not_your_child if the student isn't linked
    to this parent (so a parent can't enumerate other families' children by id)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="A parent's child's attendance / payment / rank report",
        responses={200: OpenApiResponse(description="{attendance, payment, rank}"), 404: OpenApiResponse()},
        tags=["parents"],
    )
    def get(self, request, student_id):
        parent = _require_parent(request)
        student = selectors.students_for_parent(parent=parent).filter(pk=student_id).first()
        if student is None:
            raise NotFoundException(_("That is not one of your children."), code="not_your_child")
        return Response(student_report(student=student))
