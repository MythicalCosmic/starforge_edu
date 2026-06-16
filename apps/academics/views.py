from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.academics import selectors, services
from apps.academics.models import Subject
from apps.academics.serializers import (
    CsvImportSerializer,
    ExamResultSerializer,
    ExamSerializer,
    GradeSerializer,
    RecomputeSerializer,
    ResultEntrySerializer,
    SubjectSerializer,
    TranscriptCreateSerializer,
    TranscriptSerializer,
)
from apps.cohorts.models import Cohort
from apps.parents.models import Guardian
from apps.schedule.models import Term
from core.exceptions import PermissionException, ValidationException
from core.permissions import Role, RolePermission, default_perms, get_user_roles, has_permission_code
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet

# Honor-roll / warnings are staff-facing aggregates (never exposed to the
# students/parents who also hold `academics:read`).
_REPORT_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT, Role.TEACHER}


class SubjectViewSet(TenantSafeModelViewSet):
    queryset = Subject.objects.select_related("department")
    serializer_class = SubjectSerializer
    resource = "academics"
    filterset_fields = ("is_active", "department")
    search_fields = ("name", "code")
    ordering_fields = ("name", "code")


class ExamViewSet(TenantSafeModelViewSet):
    serializer_class = ExamSerializer
    resource = "academics"
    required_perms = {
        **default_perms("academics"),
        # Raw per-student results are staff/teacher-facing on read AND write —
        # gating GET at `academics:write` avoids leaking a cohort's scores to the
        # students/parents who hold `academics:read`.
        "results": "academics:write",
        "import_csv": "academics:write",
        "publish": "academics:write",
    }
    filterset_fields = ("subject", "cohort", "term", "type", "is_published")
    ordering_fields = ("exam_date",)

    def get_queryset(self):
        # Cohort-scoped: a TEACHER only reaches exams of cohorts they teach, so
        # list/retrieve/update AND the results/import_csv/publish actions (all via
        # self.get_object()) 404 for out-of-cohort exams. Staff/superuser see all.
        return selectors.scoped_exams(user=self.request.user, roles=get_user_roles(self.request))

    @extend_schema(methods=["GET"], responses=ExamResultSerializer(many=True), tags=["academics"])
    @extend_schema(
        methods=["POST"],
        request=ResultEntrySerializer(many=True),
        responses={200: OpenApiResponse(description="{created, updated, results}"), 422: OpenApiResponse()},
        tags=["academics"],
    )
    @action(detail=True, methods=["get", "post"])
    def results(self, request, pk=None):
        exam = self.get_object()
        if request.method == "GET":
            qs = exam.results.select_related("student__user")
            return Response(ExamResultSerializer(qs, many=True).data)
        serializer = ResultEntrySerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        result = services.record_results(exam=exam, rows=serializer.validated_data, actor=request.user)
        return Response(
            {
                "created": result["created"],
                "updated": result["updated"],
                "results": ExamResultSerializer(result["results"], many=True).data,
            }
        )

    @extend_schema(
        request=CsvImportSerializer,
        responses={200: OpenApiResponse(description="{created, updated}"), 422: OpenApiResponse()},
        tags=["academics"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="results/import-csv",
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_csv(self, request, pk=None):
        exam = self.get_object()
        serializer = CsvImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.bulk_grade_import(
            exam=exam, csv_file=serializer.validated_data["file"], actor=request.user
        )
        return Response({"created": result["created"], "updated": result["updated"]})

    @extend_schema(responses=ExamSerializer, tags=["academics"])
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        exam = services.publish_exam(exam=self.get_object(), actor=request.user)
        return Response(ExamSerializer(exam).data)


class GradeViewSet(TenantSafeModelViewSet):
    """Read-only computed grades (publication-gated, role-scoped)."""

    serializer_class = GradeSerializer
    resource = "academics"
    http_method_names = ["get", "head", "options"]
    filterset_fields = ("student", "subject", "term", "is_published")
    ordering_fields = ("computed_at", "value_raw")

    def get_queryset(self):
        return selectors.scoped_grades(user=self.request.user, roles=get_user_roles(self.request))


class GradeRecomputeView(TenantSafeAPIView):
    """POST /grades/recompute/ {cohort, subject, term, publish?}."""

    permission_classes = [RolePermission]
    resource = "academics"
    required_perms = {"post": "academics:write"}

    @extend_schema(
        request=RecomputeSerializer,
        responses={200: OpenApiResponse(description="{recomputed}")},
        tags=["academics"],
    )
    def post(self, request):
        serializer = RecomputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cohort = get_object_or_404(Cohort, pk=data["cohort"])
        subject = get_object_or_404(Subject, pk=data["subject"])
        term = get_object_or_404(Term, pk=data["term"])
        grades = services.recompute_cohort_term(
            cohort=cohort, subject=subject, term=term, publish=data["publish"]
        )
        return Response({"recomputed": len(grades)})


class TranscriptViewSet(TenantSafeModelViewSet):
    """POST creates a pending transcript (+enqueues PDF); GET retrieves status +
    a signed `download_url` once done."""

    serializer_class = TranscriptSerializer
    resource = "academics"
    http_method_names = ["get", "post", "head", "options"]
    # `create` is gated at read (self/child); requesting ANOTHER student requires
    # write — enforced inside create().
    required_perms = {"list": "academics:read", "retrieve": "academics:read", "create": "academics:read"}

    def get_queryset(self):
        return selectors.scoped_transcripts(user=self.request.user, roles=get_user_roles(self.request))

    @extend_schema(
        request=TranscriptCreateSerializer,
        responses={202: OpenApiResponse(description="{id, status}")},
        tags=["academics"],
    )
    def create(self, request, *args, **kwargs):
        serializer = TranscriptCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = serializer.validated_data["student"]
        term = serializer.validated_data.get("term")
        if not self._is_self_or_child(request, student) and not has_permission_code(
            get_user_roles(request), "academics:write"
        ):
            raise PermissionException(
                "Requesting another student's transcript requires write access.", code="forbidden"
            )
        transcript = services.request_transcript(student=student, term=term, requested_by=request.user)
        return Response({"id": transcript.id, "status": transcript.status}, status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _is_self_or_child(request, student) -> bool:
        user = request.user
        if student.user_id == user.id:
            return True
        return Guardian.objects.filter(student=student, parent__user=user).exists()


class HonorRollView(TenantSafeAPIView):
    permission_classes = [RolePermission]
    resource = "academics"
    required_perms = {"get": "academics:read"}

    @extend_schema(
        parameters=[OpenApiParameter("term", int, required=True)],
        responses=GradeSerializer(many=True),
        tags=["academics"],
    )
    def get(self, request):
        _assert_report_access(request)
        term_id = _require_int(request, "term")
        grades = selectors.honor_roll(term_id=term_id, user=request.user, roles=get_user_roles(request))
        return Response(GradeSerializer(grades, many=True).data)


class WarningsView(TenantSafeAPIView):
    permission_classes = [RolePermission]
    resource = "academics"
    required_perms = {"get": "academics:read"}

    @extend_schema(
        parameters=[OpenApiParameter("term", int, required=True)],
        responses=GradeSerializer(many=True),
        tags=["academics"],
    )
    def get(self, request):
        _assert_report_access(request)
        term_id = _require_int(request, "term")
        grades = selectors.academic_warnings(
            term_id=term_id, user=request.user, roles=get_user_roles(request)
        )
        return Response(GradeSerializer(grades, many=True).data)


def _assert_report_access(request) -> None:
    if request.user.is_superuser or (get_user_roles(request) & _REPORT_ROLES):
        return
    raise PermissionException("Honor roll and warnings are staff-only.", code="forbidden")


def _require_int(request, name: str) -> int:
    raw = request.query_params.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationException(
            f"Query parameter '{name}' is required and must be an integer.",
            code="invalid_query_param",
            fields={name: ["This query parameter is required."]},
        ) from exc
