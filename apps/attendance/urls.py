from rest_framework.routers import DefaultRouter

from .views import AttendanceItemViewSet

router = DefaultRouter()
router.register(r"", AttendanceItemViewSet, basename="attendance")

urlpatterns = router.urls
