from rest_framework.routers import DefaultRouter

from apps.compliance.views import PenaltyViewSet, RuleViewSet

router = DefaultRouter()
router.register("rules", RuleViewSet, basename="rule")
router.register("penalties", PenaltyViewSet, basename="penalty")

urlpatterns = router.urls
