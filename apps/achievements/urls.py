from rest_framework.routers import DefaultRouter

from apps.achievements.views import AchievementViewSet

router = DefaultRouter()
router.register("", AchievementViewSet, basename="achievements")

urlpatterns = router.urls
