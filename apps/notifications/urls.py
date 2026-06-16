from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.notifications.views import (
    AnnouncementView,
    NotificationPreferencesView,
    NotificationTemplateViewSet,
    NotificationViewSet,
)

router = DefaultRouter()
# Templates first so its `templates/` prefix is distinct from the bare feed.
router.register("templates", NotificationTemplateViewSet, basename="notification-template")
router.register("", NotificationViewSet, basename="notification")

urlpatterns = [
    # Explicit routes must precede the router's bare `{pk}` patterns.
    path("preferences/", NotificationPreferencesView.as_view(), name="notification-preferences"),
    path("announcements/", AnnouncementView.as_view(), name="notification-announcements"),
    *router.urls,
]
