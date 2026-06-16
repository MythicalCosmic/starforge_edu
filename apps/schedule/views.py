import django_filters
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.schedule import selectors, services
from apps.schedule.models import Lesson, RecurrenceRule, Term, TimeSlot
from apps.schedule.serializers import (
    BulkRescheduleSerializer,
    CancelLessonSerializer,
    LessonSerializer,
    MoveLessonSerializer,
    RecurrenceRuleSerializer,
    RecurrenceRuleWriteSerializer,
    TermSerializer,
    TimeSlotSerializer,
)
from core.permissions import default_perms, get_user_roles
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet


class TermViewSet(TenantSafeModelViewSet):
    queryset = Term.objects.all()
    serializer_class = TermSerializer
    resource = "schedule"
    filterset_fields = ("academic_year", "is_current")
    search_fields = ("name", "academic_year")
    ordering_fields = ("start_date", "name")


class TimeSlotViewSet(TenantSafeModelViewSet):
    queryset = TimeSlot.objects.select_related("branch")
    serializer_class = TimeSlotSerializer
    resource = "schedule"
    object_scope = "branch"
    filterset_fields = ("branch",)
    ordering_fields = ("order", "start_time")


class RecurrenceRuleViewSet(TenantSafeModelViewSet):
    queryset = RecurrenceRule.objects.select_related("term", "cohort", "teacher__user", "room")
    serializer_class = RecurrenceRuleSerializer
    resource = "schedule"
    required_perms = {**default_perms("schedule"), "bulk_reschedule": "schedule:write"}
    filterset_fields = ("term", "cohort", "teacher", "is_active")
    ordering_fields = ("created_at",)

    @extend_schema(
        summary="Create a recurrence rule (materializes lessons; 409 on conflict)",
        request=RecurrenceRuleWriteSerializer,
        responses={201: RecurrenceRuleSerializer, 409: OpenApiResponse(description="schedule_conflict")},
        tags=["schedule"],
    )
    def create(self, request, *args, **kwargs):
        serializer = RecurrenceRuleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = services.create_rule(created_by=request.user, **serializer.validated_data)
        return Response(RecurrenceRuleSerializer(rule).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=RecurrenceRuleWriteSerializer, responses=RecurrenceRuleSerializer, tags=["schedule"]
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        rule = self.get_object()
        serializer = RecurrenceRuleWriteSerializer(rule, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        rule = services.update_rule(rule, **serializer.validated_data)
        return Response(RecurrenceRuleSerializer(rule).data)

    @extend_schema(
        summary="Shift every future lesson of the rule (all-or-nothing)",
        request=BulkRescheduleSerializer,
        responses={
            200: OpenApiResponse(description="{moved_count}"),
            409: OpenApiResponse(description="conflict"),
        },
        tags=["schedule"],
    )
    @action(detail=True, methods=["post"], url_path="bulk-reschedule")
    def bulk_reschedule(self, request, pk=None):
        rule = self.get_object()
        serializer = BulkRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        moved = services.bulk_reschedule(
            rule, shift_minutes=serializer.validated_data["shift_minutes"], actor=request.user
        )
        return Response({"moved_count": moved})


class LessonFilter(django_filters.FilterSet):
    date_from = django_filters.IsoDateTimeFilter(field_name="starts_at", lookup_expr="gte")
    date_to = django_filters.IsoDateTimeFilter(field_name="starts_at", lookup_expr="lte")

    class Meta:
        model = Lesson
        fields = ("cohort", "teacher", "room", "status", "term")


class LessonViewSet(TenantSafeModelViewSet):
    serializer_class = LessonSerializer
    resource = "schedule"
    http_method_names = ["get", "post", "head", "options"]
    required_perms = {**default_perms("schedule"), "cancel": "schedule:write", "move": "schedule:write"}
    filterset_class = LessonFilter
    ordering_fields = ("starts_at",)

    def get_queryset(self):
        return selectors.scoped_lessons(user=self.request.user, roles=get_user_roles(self.request))

    @extend_schema(request=CancelLessonSerializer, responses=LessonSerializer, tags=["schedule"])
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        lesson = self.get_object()
        serializer = CancelLessonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lesson = services.cancel_occurrence(
            lesson, reason=serializer.validated_data["reason"], actor=request.user
        )
        return Response(LessonSerializer(lesson).data)

    @extend_schema(
        request=MoveLessonSerializer,
        responses={200: LessonSerializer, 409: OpenApiResponse(description="schedule_conflict")},
        tags=["schedule"],
    )
    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        lesson = self.get_object()
        serializer = MoveLessonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lesson = services.move_occurrence(
            lesson,
            starts_at=serializer.validated_data["starts_at"],
            ends_at=serializer.validated_data["ends_at"],
            actor=request.user,
        )
        return Response(LessonSerializer(lesson).data)


class IcalUrlView(TenantSafeAPIView):
    """GET /api/v1/schedule/ical-url/ — a signed, tenant-bound feed URL."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get a personal iCal feed URL",
        responses={200: OpenApiResponse(description="{url}")},
        tags=["schedule"],
    )
    def get(self, request):
        token = services.ical_token_for(request.user)
        url = request.build_absolute_uri(f"/api/v1/schedule/ical/{token}/")
        return Response({"url": url})


class IcalFeedView(APIView):
    """GET /api/v1/schedule/ical/<token>/ — AllowAny, token-authed, text/calendar."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        summary="Personal iCal feed",
        responses={200: OpenApiResponse(description="text/calendar")},
        tags=["schedule"],
    )
    def get(self, request, token: str):
        lessons = services.lessons_for_token(token)
        return HttpResponse(services.build_ical(lessons), content_type="text/calendar")
