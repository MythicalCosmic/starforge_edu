from rest_framework.routers import DefaultRouter

from apps.placement.views import PlacementTestViewSet

router = DefaultRouter()
router.register("tests", PlacementTestViewSet, basename="placement-test")

urlpatterns = router.urls
