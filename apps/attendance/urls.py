from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AttendanceExportView,
    AttendanceRecordViewSet,
    AttendanceSummaryView,
    CohortDashboardView,
    MarkAttendanceView,
)

router = DefaultRouter()
router.register("records", AttendanceRecordViewSet, basename="attendance-record")

urlpatterns = [
    path("lessons/<int:lesson_id>/mark/", MarkAttendanceView.as_view(), name="attendance-mark"),
    path("summary/", AttendanceSummaryView.as_view(), name="attendance-summary"),
    path(
        "cohorts/<int:cohort_id>/dashboard/",
        CohortDashboardView.as_view(),
        name="attendance-dashboard",
    ),
    path("export/", AttendanceExportView.as_view(), name="attendance-export"),
    *router.urls,
]
