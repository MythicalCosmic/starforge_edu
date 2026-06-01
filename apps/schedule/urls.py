from rest_framework.routers import DefaultRouter

from .views import HolidayViewSet, LessonViewSet

router = DefaultRouter()
router.register(r"holidays", HolidayViewSet, basename="holidays")
router.register(r"lessons", LessonViewSet, basename="lessons")

urlpatterns = router.urls
