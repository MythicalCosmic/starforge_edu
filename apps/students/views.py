from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.students import selectors, services
from apps.students.serializers import (
    BirthdayQuerySerializer,
    EnrollmentEventSerializer,
    StudentCreateSerializer,
    StudentDetailSerializer,
    StudentImportSerializer,
    StudentReadSerializer,
    StudentUpdateSerializer,
    TransitionSerializer,
)
from core.permissions import default_perms, get_user_roles
from core.viewsets import TenantSafeModelViewSet


class StudentViewSet(TenantSafeModelViewSet):
    resource = "students"
    object_scope = "branch"
    required_perms = {
        **default_perms("students"),
        "transition": "students:write",
        "import_students": "students:write",
        "birthdays": "students:read",
        "events": "students:read",
    }
    filterset_fields = ("status", "branch", "current_cohort")
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
    @action(detail=False, methods=["post"], url_path="import")
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
        summary="A student's enrollment history",
        responses=EnrollmentEventSerializer(many=True),
        tags=["students"],
    )
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        student = self.get_object()
        events = student.enrollment_events.all()
        return Response(EnrollmentEventSerializer(events, many=True).data)
