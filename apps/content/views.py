from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.content import selectors, services
from apps.content.models import ContentLesson, ContentLibrary, Course, Folder, LessonFile, Module
from apps.content.selectors import REVIEWER_ROLES
from apps.content.serializers import (
    ApproveManagerSerializer,
    ContentLessonSerializer,
    ContentLibrarySerializer,
    ContentUploadUrlSerializer,
    CourseSerializer,
    FolderSerializer,
    LessonFileSerializer,
    ModuleSerializer,
    NewVersionSerializer,
)
from core.permissions import RolePermission, get_user_roles
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
