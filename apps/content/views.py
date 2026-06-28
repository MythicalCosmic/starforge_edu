from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.content import selectors, services
from apps.content.models import (
    ContentLesson,
    ContentLibrary,
    Course,
    Folder,
    LessonFile,
    LibraryMaterial,
    Module,
)
from apps.content.selectors import REVIEWER_ROLES
from apps.content.serializers import (
    ApproveManagerSerializer,
    ContentLessonSerializer,
    ContentLibrarySerializer,
    ContentUploadUrlSerializer,
    CourseSerializer,
    CreateMaterialSerializer,
    FolderSerializer,
    LessonFileSerializer,
    LibraryMaterialSerializer,
    ModuleSerializer,
    NewVersionSerializer,
    UpdateMaterialSerializer,
)
from core.exceptions import PermissionException
from core.permissions import RolePermission, get_user_roles, has_permission_code
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet


def _libs(request):
    return selectors.scoped_libraries(user=request.user, roles=get_user_roles(request))


class ContentLibraryViewSet(TenantSafeModelViewSet):
    queryset = ContentLibrary.objects.none()  # schema introspection; get_queryset scopes real calls
    serializer_class = ContentLibrarySerializer
    resource = "content"
    filterset_fields = ("visibility", "department", "cohort", "is_active")
    search_fields = ("name",)

    def get_queryset(self):
        return _libs(self.request)


class CourseViewSet(TenantSafeModelViewSet):
    queryset = Course.objects.none()
    serializer_class = CourseSerializer
    resource = "content"
    filterset_fields = ("library", "subject")
    search_fields = ("title",)

    def get_queryset(self):
        return Course.objects.filter(library__in=_libs(self.request)).select_related("subject")


class ModuleViewSet(TenantSafeModelViewSet):
    queryset = Module.objects.none()
    serializer_class = ModuleSerializer
    resource = "content"
    filterset_fields = ("course",)

    def get_queryset(self):
        return Module.objects.filter(course__library__in=_libs(self.request))


class ContentLessonViewSet(TenantSafeModelViewSet):
    queryset = ContentLesson.objects.none()
    serializer_class = ContentLessonSerializer
    resource = "content"
    filterset_fields = ("module",)
    search_fields = ("title",)

    def get_queryset(self):
        return ContentLesson.objects.filter(module__course__library__in=_libs(self.request))


class FolderViewSet(TenantSafeModelViewSet):
    queryset = Folder.objects.none()
    serializer_class = FolderSerializer
    resource = "content"
    filterset_fields = ("library", "parent")

    def get_queryset(self):
        return Folder.objects.filter(library__in=_libs(self.request))


class LessonFileViewSet(TenantSafeModelViewSet):
    """Read (visibility-scoped) + the signed-URL upload/download flow. Files are
    created only through `upload-url` / `new-version`, never a bare POST."""

    queryset = LessonFile.objects.none()
    serializer_class = LessonFileSerializer
    resource = "content"
    http_method_names = ["get", "post", "head", "options"]
    required_perms = {
        "list": "content:read",
        "retrieve": "content:read",
        "create": "content:write",
        "confirm": "content:write",
        "new_version": "content:write",
        "download_url": "content:read",
        "track_view": "content:read",
        # F4-5: teacher leg vs manager leg = two distinct permission codes (and
        # the manager leg is further gated on a manager role in the service).
        "approve_teacher": "content:approve",
        "approve_manager": "content:publish",
    }
    filterset_fields = ("status", "lesson", "folder")

    def get_queryset(self):
        return selectors.scoped_files(user=self.request.user, roles=get_user_roles(self.request))

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST", detail="Upload via /content/upload-url/.")

    @extend_schema(
        responses={202: OpenApiResponse(description="{status: pending}"), 409: OpenApiResponse()},
        tags=["content"],
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        services.confirm_upload(file=self.get_object())
        return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        responses={200: OpenApiResponse(description="{url, expires_in}"), 409: OpenApiResponse()},
        tags=["content"],
    )
    @action(detail=True, methods=["get"], url_path="download-url")
    def download_url(self, request, pk=None):
        # F4-5: content staff may still download a view-only file to manage it.
        is_staff = request.user.is_superuser or bool(get_user_roles(request) & REVIEWER_ROLES)
        result = services.download_url(
            file=self.get_object(), user=request.user, actor_is_staff=is_staff
        )
        return Response(result)

    @extend_schema(responses={204: OpenApiResponse(description="tracked")}, tags=["content"])
    @action(detail=True, methods=["post"], url_path="track-view")
    def track_view(self, request, pk=None):
        services.track_view(file=self.get_object(), user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=NewVersionSerializer,
        responses={200: OpenApiResponse(description="{file_id, url, key, expires_in}")},
        tags=["content"],
    )
    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request, pk=None):
        serializer = NewVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.create_new_version(
            previous=self.get_object(), user=request.user, **serializer.validated_data
        )
        return Response(_upload_payload(result))

    @extend_schema(request=None, responses={200: LessonFileSerializer}, tags=["content"])
    @action(detail=True, methods=["post"], url_path="approve-teacher")
    def approve_teacher(self, request, pk=None):
        """F4-5 first sign-off: a teacher vouches for the file."""
        file = services.approve_teacher_leg(file=self.get_object(), actor=request.user)
        return Response(LessonFileSerializer(file).data)

    @extend_schema(
        request=ApproveManagerSerializer, responses={200: LessonFileSerializer}, tags=["content"]
    )
    @action(detail=True, methods=["post"], url_path="approve-manager")
    def approve_manager(self, request, pk=None):
        """F4-5 second sign-off (publishes to learners): a manager counter-signs
        a different person's teacher approval, optionally as view-only."""
        ser = ApproveManagerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        file = services.approve_manager_leg(
            file=self.get_object(),
            actor=request.user,
            actor_roles=get_user_roles(request),
            is_downloadable=ser.validated_data.get("is_downloadable"),
        )
        return Response(LessonFileSerializer(file).data)


class ContentUploadUrlView(TenantSafeAPIView):
    """POST /content/upload-url/ — validate + presign a new upload."""

    permission_classes = [RolePermission]
    resource = "content"
    required_perms = {"post": "content:write"}

    @extend_schema(
        request=ContentUploadUrlSerializer,
        responses={
            200: OpenApiResponse(description="{file_id, url, key, expires_in}"),
            422: OpenApiResponse(),
        },
        tags=["content"],
    )
    def post(self, request):
        serializer = ContentUploadUrlSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.request_upload(
            filename=data["filename"],
            content_type=data["content_type"],
            size_bytes=data["size_bytes"],
            user=request.user,
            lesson=data.get("lesson"),
            folder=data.get("folder"),
            title=data.get("title"),
        )
        return Response(_upload_payload(result))


def _upload_payload(result: dict) -> dict:
    return {
        "file_id": result["file"].id,
        "url": result["url"],
        "key": result["key"],
        "expires_in": result["expires_in"],
    }


class LibraryMaterialViewSet(TenantSafeModelViewSet):
    """AI-drafted teaching materials (F9-1). A manager (content:write) creates a DRAFT,
    optionally has the AI draft its body (generate), hand-edits it, then publishes it
    (content:publish — a human still signs off). Learners (content:read) see only
    PUBLISHED materials in libraries they can access; a half-written draft never leaks."""

    queryset = LibraryMaterial.objects.none()
    serializer_class = LibraryMaterialSerializer
    resource = "content"
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_perms = {
        "list": "content:read",
        "retrieve": "content:read",
        "create": "content:write",
        "partial_update": "content:write",
        "generate": "content:write",
        "publish": "content:publish",
    }
    filterset_fields = ("library", "status")
    search_fields = ("title",)

    def get_queryset(self):
        qs = LibraryMaterial.objects.filter(library__in=_libs(self.request)).select_related(
            "library", "created_by"
        )
        roles = get_user_roles(self.request)
        # Content STAFF — anyone who writes, approves, or PUBLISHES — see DRAFTs too. This
        # must include the publisher who holds content:publish WITHOUT content:write (the
        # HOD), or the designated publisher could never reach a draft to publish it.
        # Learners (content:read only) see PUBLISHED materials only — no half-written draft.
        manages_content = self.request.user.is_superuser or any(
            has_permission_code(roles, c) for c in ("content:write", "content:approve", "content:publish")
        )
        if not manages_content:
            qs = qs.filter(status=LibraryMaterial.Status.PUBLISHED)
        return qs

    def _assert_library_writable(self, library):
        if library not in _libs(self.request):
            raise PermissionException(
                _("You can only add materials to a library you can access."),
                code="library_out_of_scope",
            )

    @extend_schema(request=CreateMaterialSerializer, responses={201: LibraryMaterialSerializer}, tags=["content"])
    def create(self, request, *args, **kwargs):
        ser = CreateMaterialSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self._assert_library_writable(ser.validated_data["library"])
        material = services.create_material(
            library=ser.validated_data["library"],
            title=ser.validated_data["title"],
            topic=ser.validated_data.get("topic", ""),
            created_by=request.user,
        )
        return Response(LibraryMaterialSerializer(material).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=UpdateMaterialSerializer, responses={200: LibraryMaterialSerializer}, tags=["content"])
    def partial_update(self, request, *args, **kwargs):
        material = self.get_object()  # scoped via get_queryset; the service locks + re-checks
        ser = UpdateMaterialSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        material = services.update_material(material_id=material.pk, fields=ser.validated_data)
        return Response(LibraryMaterialSerializer(material).data)

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(description="{request_id, status} — poll /ai/requests/{id}/")},
        tags=["content"],
    )
    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        """F9-1: have the AI draft this DRAFT material's body (async). Reviewed + published
        by a human afterwards."""
        ai_request = services.request_material_generation(
            material=self.get_object(), requested_by=request.user
        )
        return Response(
            {"request_id": ai_request.pk, "status": ai_request.status}, status=status.HTTP_202_ACCEPTED
        )

    @extend_schema(request=None, responses={200: LibraryMaterialSerializer}, tags=["content"])
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        material = services.publish_material(material=self.get_object())
        return Response(LibraryMaterialSerializer(material).data)
