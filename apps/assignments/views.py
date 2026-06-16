from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.assignments import selectors, services
from apps.assignments.serializers import (
    AssignmentSerializer,
    GradeInputSerializer,
    SubmissionCreateSerializer,
    SubmissionGradeSerializer,
    SubmissionSerializer,
    UploadUrlSerializer,
)
from apps.students.models import StudentProfile
from core.exceptions import PermissionException
from core.permissions import default_perms, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


def _require(request, code: str) -> None:
    if not has_permission_code(get_user_roles(request), code):
        raise PermissionException(code="forbidden")


def _require_any(request, codes: list[str]) -> None:
    roles = get_user_roles(request)
    if not any(has_permission_code(roles, c) for c in codes):
        raise PermissionException(code="forbidden")


class AssignmentViewSet(TenantSafeModelViewSet):
    serializer_class = AssignmentSerializer
    resource = "assignments"
    required_perms = {
        **default_perms("assignments"),
        "publish": "assignments:write",
        # Method-specific floors (read), then explicit write/submit gating inside.
        "submissions": "assignments:read",
        "upload_url": "assignments:read",
    }
    filterset_fields = ("cohort", "status")
    ordering_fields = ("due_at", "created_at")

    def get_queryset(self):
        return selectors.scoped_assignments(user=self.request.user, roles=get_user_roles(self.request))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @extend_schema(responses=AssignmentSerializer, tags=["assignments"])
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        assignment = services.publish_assignment(assignment=self.get_object(), actor=request.user)
        return Response(AssignmentSerializer(assignment).data)

    @extend_schema(methods=["GET"], responses=SubmissionSerializer(many=True), tags=["assignments"])
    @extend_schema(
        methods=["POST"],
        request=SubmissionCreateSerializer,
        responses={201: SubmissionSerializer, 422: OpenApiResponse()},
        tags=["assignments"],
    )
    @action(detail=True, methods=["get", "post"])
    def submissions(self, request, pk=None):
        assignment = self.get_object()  # scoped → drafts / other cohorts 404 here
        if request.method == "GET":
            _require(request, "assignments:write")  # teacher list
            qs = selectors.scoped_submissions(user=request.user, roles=get_user_roles(request)).filter(
                assignment=assignment
            )
            return Response(SubmissionSerializer(qs, many=True).data)

        _require(request, "assignments:submit")  # student submit
        student = StudentProfile.objects.filter(user=request.user).first()
        if student is None:
            raise PermissionException("Only an enrolled student may submit.", code="not_a_student")
        serializer = SubmissionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = services.submit(
            assignment=assignment,
            student=student,
            text=serializer.validated_data["text"],
            attachment_keys=serializer.validated_data["attachment_keys"],
        )
        return Response(SubmissionSerializer(submission).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=UploadUrlSerializer,
        responses={200: OpenApiResponse(description="{url, key}"), 422: OpenApiResponse()},
        tags=["assignments"],
    )
    @action(detail=False, methods=["post"], url_path="upload-url")
    def upload_url(self, request):
        _require_any(request, ["assignments:write", "assignments:submit"])
        serializer = UploadUrlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.validate_and_presign_upload(**serializer.validated_data)
        return Response(result)


# The documented submission list is the nested `/assignments/{id}/submissions/`
# action; the bare collection list/create here are undocumented (create is 405).
@extend_schema_view(list=extend_schema(exclude=True), create=extend_schema(exclude=True))
class SubmissionViewSet(TenantSafeModelViewSet):
    """Retrieve a submission (owner student or cohort teacher) + grade /
    request-ai-feedback actions. No generic create — submissions are made via
    `/assignments/{id}/submissions/`."""

    serializer_class = SubmissionSerializer
    resource = "assignments"
    http_method_names = ["get", "post", "head", "options"]
    required_perms = {
        **default_perms("assignments"),
        "grade": "assignments:write",
        "request_ai_feedback": "assignments:write",
    }

    def get_queryset(self):
        return selectors.scoped_submissions(user=self.request.user, roles=get_user_roles(self.request))

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST", detail="Submit via /assignments/{id}/submissions/.")

    @extend_schema(
        request=GradeInputSerializer,
        responses={200: SubmissionGradeSerializer, 422: OpenApiResponse()},
        tags=["assignments"],
    )
    @action(detail=True, methods=["post"])
    def grade(self, request, pk=None):
        submission = self.get_object()
        serializer = GradeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grade = services.grade_submission(
            submission=submission,
            score=serializer.validated_data["score"],
            rubric_scores=serializer.validated_data["rubric_scores"],
            feedback=serializer.validated_data["feedback"],
            actor=request.user,
        )
        return Response(SubmissionGradeSerializer(grade).data)

    @extend_schema(responses={202: OpenApiResponse(description="{status: queued}")}, tags=["assignments"])
    @action(detail=True, methods=["post"], url_path="request-ai-feedback")
    def request_ai_feedback(self, request, pk=None):
        submission = self.get_object()
        services.request_ai_feedback(submission=submission, requested_by=request.user)
        return Response({"status": "queued"}, status=status.HTTP_202_ACCEPTED)
