from rest_framework.routers import DefaultRouter

from apps.meetings.views import StaffMeetingViewSet

router = DefaultRouter()
router.register("", StaffMeetingViewSet, basename="meetings")

urlpatterns = router.urls
