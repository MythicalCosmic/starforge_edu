from rest_framework.routers import DefaultRouter

from apps.compliance.views import RuleViewSet

router = DefaultRouter()
router.register("rules", RuleViewSet, basename="rule")

urlpatterns = router.urls
