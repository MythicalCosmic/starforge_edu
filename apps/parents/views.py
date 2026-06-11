from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.parents import selectors, services
from apps.parents.models import PickupAuthorization
from apps.parents.serializers import (
    GuardianReadSerializer,
    GuardianWriteSerializer,
    ParentCreateSerializer,
    ParentReadSerializer,
    ParentUpdateSerializer,
    PickupAuthorizationSerializer,
)
from apps.students.serializers import StudentReadSerializer
from core.permissions import default_perms, get_user_roles
from core.viewsets import TenantSafeModelViewSet


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
    queryset = PickupAuthorization.objects.select_related("student__user")
    serializer_class = PickupAuthorizationSerializer
    filterset_fields = ("student", "is_active")
    ordering_fields = ("created_at",)
