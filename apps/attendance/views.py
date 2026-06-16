from __future__ import annotations

import csv

import django_filters
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response

from apps.attendance import selectors, services
from apps.attendance.models import AttendanceRecord
from apps.attendance.serializers import (
    AttendanceMarkEntrySerializer,
    AttendanceRecordSerializer,
    AttendanceSummarySerializer,
)
from apps.cohorts.models import Cohort
from apps.schedule.models import Lesson
from core.exceptions import PermissionException, ValidationException
from core.permissions import Role, RolePermission, get_user_roles
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet

# Staff who may view a whole-cohort dashboard; a teacher additionally qualifies
# for cohorts they teach (checked per-request). Students/parents never do.
_DASHBOARD_STAFF = selectors.STAFF_ROLES


class AttendanceFilter(django_filters.FilterSet):
    cohort = django_filters.NumberFilter(field_name="lesson__cohort_id")
    date_from = django_filters.IsoDateTimeFilter(field_name="lesson__starts_at", lookup_expr="gte")
    date_to = django_filters.IsoDateTimeFilter(field_name="lesson__starts_at", lookup_expr="lte")

    class Meta:
        model = AttendanceRecord
        fields = ("student", "lesson", "status", "cohort")


class AttendanceRecordViewSet(TenantSafeModelViewSet):
    """GET /records/ + /records/{id}/ — read-only, role-scoped (read_self /
    read_own_children via `scoped_records`)."""

    serializer_class = AttendanceRecordSerializer
    resource = "attendance"
    http_method_names = ["get", "head", "options"]
    filterset_class = AttendanceFilter
    ordering_fields = ("created_at", "marked_at")

    def get_queryset(self):
        return selectors.scoped_records(user=self.request.user, roles=get_user_roles(self.request))


class MarkAttendanceView(TenantSafeAPIView):
    """POST /lessons/{lesson_id}/mark/ — teacher-scoped attendance upsert."""

    permission_classes = [RolePermission]
    resource = "attendance"
    required_perms = {"post": "attendance:write"}

    @extend_schema(
        summary="Mark attendance for a lesson (upsert; auto-late from arrived_at)",
        request=AttendanceMarkEntrySerializer(many=True),
        responses={
            200: OpenApiResponse(description="{created, updated, records}"),
            403: OpenApiResponse(description="not_lesson_teacher / correction_window_expired"),
            422: OpenApiResponse(description="student_not_in_cohort"),
        },
        tags=["attendance"],
    )
    def post(self, request, lesson_id: int):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        serializer = AttendanceMarkEntrySerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        result = services.mark_attendance(
            lesson=lesson, entries=serializer.validated_data, actor=request.user
        )
        return Response(
            {
                "created": result["created"],
                "updated": result["updated"],
                "records": AttendanceRecordSerializer(result["records"], many=True).data,
            }
        )


class AttendanceSummaryView(TenantSafeAPIView):
    """GET /summary/?student=&term= — per-student per-term percentages, scoped."""

    permission_classes = [RolePermission]
    resource = "attendance"
    required_perms = {"get": "attendance:read"}

    @extend_schema(
        parameters=[
            OpenApiParameter("student", int, required=True),
            OpenApiParameter("term", int, required=True),
        ],
        responses=AttendanceSummarySerializer,
        tags=["attendance"],
    )
    def get(self, request):
        student_id = _require_int(request, "student")
        term_id = _require_int(request, "term")
        base = selectors.scoped_records(user=request.user, roles=get_user_roles(request))
        data = selectors.term_summary(base_qs=base, student_id=student_id, term_id=term_id)
        return Response(data)


class CohortDashboardView(TenantSafeAPIView):
    """GET /cohorts/{cohort_id}/dashboard/ — whole-cohort grid; staff or the
    teaching teacher only (never a student/parent)."""

    permission_classes = [RolePermission]
    resource = "attendance"
    required_perms = {"get": "attendance:read"}

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", str, required=False),
            OpenApiParameter("date_to", str, required=False),
        ],
        responses={200: OpenApiResponse(description="{cohort, rate, students:[...]}")},
        tags=["attendance"],
    )
    def get(self, request, cohort_id: int):
        self._authorize(request, cohort_id)
        data = selectors.cohort_dashboard(
            cohort_id=cohort_id,
            date_from=_parse_dt(request, "date_from"),
            date_to=_parse_dt(request, "date_to"),
        )
        return Response(data)

    @staticmethod
    def _authorize(request, cohort_id: int) -> None:
        user = request.user
        roles = get_user_roles(request)
        if user.is_superuser or roles & _DASHBOARD_STAFF:
            return
        teaches = (
            Role.TEACHER in roles
            and Cohort.objects.filter(pk=cohort_id)
            .filter(
                Q(primary_teacher__user=user)
                | Q(co_teachers__teacher__user=user)
                | Q(lessons__teacher__user=user)
            )
            .exists()
        )
        if not teaches:
            raise PermissionException(
                "You may only view dashboards for cohorts you teach.", code="not_cohort_teacher"
            )


class AttendanceExportView(TenantSafeAPIView):
    """GET /export/?cohort=&term= — streaming text/csv, role-scoped."""

    permission_classes = [RolePermission]
    resource = "attendance"
    required_perms = {"get": "attendance:read"}

    @extend_schema(
        parameters=[
            OpenApiParameter("cohort", int, required=False),
            OpenApiParameter("term", int, required=False),
        ],
        responses={200: OpenApiResponse(description="text/csv")},
        tags=["attendance"],
    )
    def get(self, request):
        qs = selectors.scoped_records(user=request.user, roles=get_user_roles(request))
        cohort = request.query_params.get("cohort")
        term = request.query_params.get("term")
        if cohort:
            qs = qs.filter(lesson__cohort_id=cohort)
        if term:
            qs = qs.filter(lesson__term_id=term)
        qs = qs.select_related("marked_by").order_by("lesson__starts_at", "student_id")

        response = StreamingHttpResponse(_csv_rows(qs), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="attendance.csv"'
        return response


def _csv_rows(records):
    writer = csv.writer(_Echo())
    yield writer.writerow(["date", "lesson", "student", "status", "marked_by"])
    for record in records.iterator():
        yield writer.writerow(
            [
                record.lesson.starts_at.date().isoformat(),
                record.lesson.title,
                record.student.user.get_full_name(),
                record.status,
                getattr(record.marked_by, "username", "") or ("auto" if record.auto_marked else ""),
            ]
        )


class _Echo:
    """Write-only file-like object that returns each row for StreamingHttpResponse."""

    def write(self, value: str) -> str:
        return value


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


def _parse_dt(request, name: str):
    """Parse an optional `date_from`/`date_to` ISO datetime query param. Returns
    `None` when absent; raises a 400 `ValidationException` on a malformed value so
    a bad input surfaces as the TD-18 envelope instead of an ORM-level 500."""
    raw = request.query_params.get(name)
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        raise ValidationException(
            f"Query parameter '{name}' must be a valid ISO 8601 datetime.",
            code="invalid_query_param",
            fields={name: ["Enter a valid ISO 8601 datetime."]},
        )
    return parsed
