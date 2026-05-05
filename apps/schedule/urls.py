from rest_framework.routers import DefaultRouter

from .views import ScheduleItemViewSet

router = DefaultRouter()
router.register(r"", ScheduleItemViewSet, basename="schedule")

urlpatterns = router.urls
