from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import TeacherDashboardView, TeacherViewSet

router = DefaultRouter()
router.register(r"", TeacherViewSet, basename="teachers")

# `dashboard/` MUST precede the router's <pk> detail route (which would otherwise
# capture "dashboard" as a teacher pk).
urlpatterns = [
    path("dashboard/", TeacherDashboardView.as_view(), name="teacher-dashboard"),
    *router.urls,
]
