from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import StudentDashboardView, StudentReportView, StudentViewSet

router = DefaultRouter()
router.register(r"", StudentViewSet, basename="students")

# The self-scoped views must precede the router so "me" is not parsed as a pk.
urlpatterns = [
    path("me/dashboard/", StudentDashboardView.as_view(), name="student-dashboard"),
    path("me/report/", StudentReportView.as_view(), name="student-report"),
    *router.urls,
]
