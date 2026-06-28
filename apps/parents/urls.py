from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    GuardianViewSet,
    ParentChildrenView,
    ParentChildReportView,
    ParentViewSet,
    PickupAuthorizationViewSet,
)

router = DefaultRouter()
# Specific routes before the catch-all "" parent route.
router.register(r"guardians", GuardianViewSet, basename="guardian")
router.register(r"pickups", PickupAuthorizationViewSet, basename="pickup")
router.register(r"", ParentViewSet, basename="parents")

urlpatterns = [
    # Parent self-service (F2-6) — declared BEFORE the router so "me" isn't read as a
    # parent pk by the catch-all ParentViewSet detail route.
    path("me/children/", ParentChildrenView.as_view(), name="parent-my-children"),
    path(
        "me/children/<int:student_id>/report/",
        ParentChildReportView.as_view(),
        name="parent-child-report",
    ),
    *router.urls,
]
