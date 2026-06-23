from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import StudentDashboardView, StudentViewSet

router = DefaultRouter()
router.register(r"", StudentViewSet, basename="students")

# The self-scoped dashboard must precede the router so "me" is not parsed as a pk.
urlpatterns = [
    path("me/dashboard/", StudentDashboardView.as_view(), name="student-dashboard"),
    *router.urls,
]
