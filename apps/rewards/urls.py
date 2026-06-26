from rest_framework.routers import DefaultRouter

from apps.rewards.views import RewardGrantViewSet, RewardTypeViewSet

router = DefaultRouter()
router.register("types", RewardTypeViewSet, basename="reward-types")
router.register("grants", RewardGrantViewSet, basename="reward-grants")

urlpatterns = router.urls
