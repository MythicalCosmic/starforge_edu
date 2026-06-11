from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    BranchTransferViewSet,
    BranchViewSet,
    CenterSettingsView,
    DepartmentViewSet,
    RoomViewSet,
)

router = DefaultRouter()
router.register(r"branches", BranchViewSet, basename="branch")
router.register(r"departments", DepartmentViewSet, basename="department")
router.register(r"rooms", RoomViewSet, basename="room")
router.register(r"transfers", BranchTransferViewSet, basename="transfer")

urlpatterns = [
    path("settings/", CenterSettingsView.as_view(), name="center-settings"),
    *router.urls,
]
