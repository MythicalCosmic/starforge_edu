from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import PermissionException
from core.permissions import get_user_roles, has_permission_code
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet

from . import services
from .models import Branch, BranchTransfer, CenterSettings, Department, Room
from .selectors import get_center_settings
from .serializers import (
    BranchDetailSerializer,
    BranchSerializer,
    BranchTransferSerializer,
    CenterSettingsSerializer,
    DepartmentSerializer,
    HolidaySerializer,
    HolidayWriteSerializer,
    RoomSerializer,
    WorkingHoursSerializer,
    WorkingHoursWriteSerializer,
)


def _require_org_write(request) -> None:
    if request.user.is_superuser:
        return
    if not has_permission_code(get_user_roles(request), "org:write"):
        raise PermissionException()


class BranchViewSet(TenantSafeModelViewSet):
    serializer_class = BranchSerializer
    resource = "org"
    required_perms = {
        "working_hours": "org:write",
        "holidays": "org:read",
        "delete_holiday": "org:write",
    }
    filterset_fields = ("is_active",)
    search_fields = ("name", "slug", "address")
    ordering_fields = ("name", "created_at")

    def get_queryset(self):
        # Archived branches drop out of the default surface (D1-LF-7).
        return Branch.objects.filter(archived_at__isnull=True).prefetch_related(
            "departments", "working_hours"
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return BranchDetailSerializer
        return BranchSerializer

    @extend_schema(summary="Archive a branch (soft delete)", tags=["org"])
    def destroy(self, request, *args, **kwargs):
        services.archive_branch(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Replace a branch's weekly working hours",
        request=WorkingHoursWriteSerializer(many=True),
        responses=WorkingHoursSerializer(many=True),
        tags=["org"],
    )
    @action(detail=True, methods=["put"], url_path="working-hours")
    def working_hours(self, request, pk=None):
        branch = self.get_object()
        serializer = WorkingHoursWriteSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        rows = services.replace_working_hours(branch, serializer.validated_data)
        return Response(WorkingHoursSerializer(rows, many=True).data)

    @extend_schema(
        summary="List or add a branch holiday",
        request=HolidayWriteSerializer,
        responses={200: HolidaySerializer(many=True), 201: HolidaySerializer},
        tags=["org"],
    )
    @action(detail=True, methods=["get", "post"], url_path="holidays")
    def holidays(self, request, pk=None):
        branch = self.get_object()
        if request.method == "POST":
            _require_org_write(request)
            serializer = HolidayWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            holiday = branch.holidays.create(**serializer.validated_data)
            return Response(HolidaySerializer(holiday).data, status=status.HTTP_201_CREATED)
        return Response(HolidaySerializer(branch.holidays.all(), many=True).data)

    @extend_schema(summary="Delete a branch holiday", tags=["org"])
    @action(detail=True, methods=["delete"], url_path=r"holidays/(?P<holiday_id>[^/.]+)")
    def delete_holiday(self, request, pk=None, holiday_id=None):
        branch = self.get_object()
        holiday = get_object_or_404(branch.holidays, pk=holiday_id)
        holiday.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DepartmentViewSet(TenantSafeModelViewSet):
    queryset = Department.objects.select_related("branch", "head")
    serializer_class = DepartmentSerializer
    resource = "org"
    object_scope = "branch"
    filterset_fields = ("branch", "is_active")
    search_fields = ("name", "slug")
    ordering_fields = ("name", "created_at")


class RoomViewSet(TenantSafeModelViewSet):
    queryset = Room.objects.select_related("branch")
    serializer_class = RoomSerializer
    resource = "org"
    object_scope = "branch"
    filterset_fields = ("branch", "is_active")
    search_fields = ("name",)
    ordering_fields = ("name", "created_at")


class BranchTransferViewSet(TenantSafeModelViewSet):
    """Read-only audit list of branch transfers (D1-LF-6)."""

    queryset = BranchTransfer.objects.select_related("from_branch", "to_branch", "user", "actor")
    serializer_class = BranchTransferSerializer
    resource = "org"
    http_method_names = ["get", "head", "options"]
    filterset_fields = ("user", "from_branch", "to_branch")
    ordering_fields = ("created_at",)


class CenterSettingsView(TenantSafeAPIView):
    """GET/PATCH /api/v1/org/settings/ — the CenterSettings singleton (TD-13).

    APIView (not a viewset), so the per-action permission codes are enforced
    explicitly: `org:read` to read, `org:write` to update.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Read this Center's settings",
        responses=CenterSettingsSerializer,
        tags=["org"],
    )
    def get(self, request):
        self._require(request, "org:read")
        return Response(CenterSettingsSerializer(get_center_settings()).data)

    @extend_schema(
        summary="Update this Center's settings",
        request=CenterSettingsSerializer,
        responses={200: CenterSettingsSerializer, 403: OpenApiResponse(description="forbidden")},
        tags=["org"],
    )
    def patch(self, request):
        self._require(request, "org:write")
        obj = CenterSettings.load()
        serializer = CenterSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @staticmethod
    def _require(request, code: str) -> None:
        if request.user.is_superuser:
            return
        if not has_permission_code(get_user_roles(request), code):
            raise PermissionException()
