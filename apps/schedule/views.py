from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.response import Response

from core.viewsets import TenantSafeModelViewSet

from .models import Holiday, Lesson
from .serializers import HolidaySerializer, LessonSerializer, RecurringLessonSerializer
from .services import create_recurring


class HolidayViewSet(TenantSafeModelViewSet):
    queryset = Holiday.objects.select_related("branch").all()
    serializer_class = HolidaySerializer
    required_perm = "schedule:read"

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["branch", "date"]


class LessonViewSet(TenantSafeModelViewSet):
    queryset = Lesson.objects.select_related("cohort", "branch", "room", "teacher").all()
    serializer_class = LessonSerializer
    required_perm = "schedule:read"
    object_scope = "branch"

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["cohort", "branch", "room", "teacher", "status", "series_id"]
    ordering_fields = ["start", "end"]

    @action(detail=False, methods=["post"], url_path="recurring")
    def recurring(self, request):
        """Generate a weekly recurring series; skips holidays + conflicting slots."""
        serializer = RecurringLessonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        created, skipped = create_recurring(
            cohort=data["cohort"],
            room=data.get("room"),
            teacher=data.get("teacher"),
            start_time=data["start_time"],
            end_time=data["end_time"],
            weekdays=data["weekdays"],
            start_date=data["start_date"],
            end_date=data["end_date"],
            skip_holidays=data["skip_holidays"],
        )
        return Response(
            {
                "created": len(created),
                "skipped": skipped,
                "series_id": str(created[0].series_id) if created else None,
            }
        )
