from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.students import selectors, services
from apps.students.filters import StudentFilter
from apps.students.serializers import (
    BirthdayQuerySerializer,
    BlockSerializer,
    ComparisonQuerySerializer,
    EnrollmentEventSerializer,
    StudentCreateSerializer,
    StudentDetailSerializer,
    StudentImportSerializer,
    StudentReadSerializer,
    StudentUpdateSerializer,
    TransitionSerializer,
)
from core.exceptions import NotFoundException
from core.permissions import default_perms, get_user_roles
from core.throttles import BulkImportThrottle
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet


class StudentDashboardView(TenantSafeAPIView):
    """GET /api/v1/students/me/dashboard/ — the signed-in student's own cockpit
    (group, next lessons, open homework, recent grades, outstanding balance,
    outstanding rule acknowledgments). 404 not_a_student if the user isn't one."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="The signed-in student's dashboard",
        responses={200: OpenApiResponse(description="dashboard object"), 404: OpenApiResponse()},
        tags=["students"],
    )
    def get(self, request):
        student = selectors.student_profile_for(request.user)
        if student is None:
            raise NotFoundException(_("You do not have a student profile."), code="not_a_student")
        return Response(
            selectors.student_dashboard(student=student, user=request.user, roles=get_user_roles(request))
        )


class StudentViewSet(TenantSafeModelViewSet):
    resource = "students"
    object_scope = "branch"
    required_perms = {
        **default_perms("students"),
        "transition": "students:write",
        "import_students": "students:write",
        "birthdays": "students:read",
        "events": "students:read",
        "block": "students:write",
        "unblock": "students:write",
        "stats": "students:read",
        "comparison": "students:read",
    }
    filterset_class = StudentFilter
    search_fields = ("user__first_name", "user__last_name", "user__phone", "student_id")
    ordering_fields = ("created_at", "enrollment_date", "student_id")

    def get_queryset(self):
        return selectors.scoped_students(user=self.request.user, roles=get_user_roles(self.request))

    def get_serializer_class(self):
        if self.action == "create":
            return StudentCreateSerializer
        if self.action in ("update", "partial_update"):
            return StudentUpdateSerializer
        if self.action == "retrieve":
            # Role-gated medical_notes; get_serializer() supplies request context.
            return StudentDetailSerializer
        return StudentReadSerializer

    def update(self, request, *args, **kwargs):
        """Accept edits via StudentUpdateSerializer but return the role-gated
        StudentDetailSerializer so medical_notes (encrypted PHI) is NOT echoed
        back to a writer who is not a MEDICAL_NOTES_ROLE (DoD #4 / TD-11). The
        default ModelViewSet.update would return serializer.data with the
        decrypted plaintext, bypassing the retrieve-time gate."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = StudentUpdateSerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if getattr(instance, "_prefetched_objects_cache", None):
            # Drop the prefetch cache invalidated by the write (DRF parity).
            instance._prefetched_objects_cache = {}
        return Response(StudentDetailSerializer(instance, context={"request": request}).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(
        summary="Enroll a student (creates user + profile, generates student_id)",
        request=StudentCreateSerializer,
        responses={201: StudentReadSerializer},
        tags=["students"],
    )
    def create(self, request, *args, **kwargs):
        serializer = StudentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = services.create_student(**serializer.validated_data)
        return Response(StudentReadSerializer(student).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Transition a student's enrollment status",
        request=TransitionSerializer,
        responses={200: StudentReadSerializer, 400: OpenApiResponse(description="invalid_transition")},
        tags=["students"],
    )
    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        student = self.get_object()
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = services.transition_enrollment(
            student=student, actor=request.user, **serializer.validated_data
        )
        return Response(StudentReadSerializer(student).data)

    @extend_schema(
        summary="Bulk-import students from a CSV",
        request=StudentImportSerializer,
        responses={201: OpenApiResponse(description="{created, errors}")},
        tags=["students"],
    )
    @action(detail=False, methods=["post"], url_path="import", throttle_classes=[BulkImportThrottle])
    def import_students(self, request):
        serializer = StudentImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.import_students_csv(
            file_obj=serializer.validated_data["file"],
            branch=serializer.validated_data["branch"],
        )
        return Response(result, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Students with an upcoming birthday",
        responses=StudentReadSerializer(many=True),
        tags=["students"],
    )
    @action(detail=False, methods=["get"])
    def birthdays(self, request):
        params = BirthdayQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        queryset = selectors.students_with_upcoming_birthdays(
            base=selectors.scoped_students(user=request.user, roles=get_user_roles(request)),
            days=params.validated_data["days"],
            branch=params.validated_data.get("branch"),
            cohort=params.validated_data.get("cohort"),
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(StudentReadSerializer(page, many=True).data)
        return Response(StudentReadSerializer(queryset, many=True).data)

    @extend_schema(
        summary="Student-list snapshot stats (totals, with/without group, blocked, by status/branch)",
        responses={200: OpenApiResponse(description="stats object")},
        tags=["students"],
    )
    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = selectors.scoped_students(user=request.user, roles=get_user_roles(request))
        return Response(selectors.student_stats(qs))

    @extend_schema(
        summary="Compare joined/left this period vs the previous one",
        parameters=[
            OpenApiParameter("metric", str, description="joined | left (default joined)"),
            OpenApiParameter("unit", str, description="hour | day | week | month | year (default month)"),
        ],
        responses={200: OpenApiResponse(description="comparison object")},
        tags=["students"],
    )
    @action(detail=False, methods=["get"])
    def comparison(self, request):
        params = ComparisonQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        qs = selectors.scoped_students(user=request.user, roles=get_user_roles(request))
        return Response(selectors.student_comparison(qs, **params.validated_data))

    @extend_schema(
        summary="Block a student (soft bar; stays enrolled)",
        request=BlockSerializer,
        responses={200: StudentReadSerializer},
        tags=["students"],
    )
    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        student = self.get_object()
        ser = BlockSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        student = services.block_student(
            student=student, reason=ser.validated_data["reason"], actor=request.user
        )
        return Response(StudentReadSerializer(student).data)

    @extend_schema(
        summary="Unblock a student",
        request=None,
        responses={200: StudentReadSerializer},
        tags=["students"],
    )
    @action(detail=True, methods=["post"])
    def unblock(self, request, pk=None):
        student = self.get_object()
        student = services.unblock_student(student=student, actor=request.user)
        return Response(StudentReadSerializer(student).data)

    @extend_schema(
        summary="A student's enrollment history",
        responses=EnrollmentEventSerializer(many=True),
        tags=["students"],
    )
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        student = self.get_object()
        events = student.enrollment_events.all()
        return Response(EnrollmentEventSerializer(events, many=True).data)
