from rest_framework.routers import DefaultRouter

from apps.placement.views import (
    GroupProposalViewSet,
    PlacementAttemptViewSet,
    PlacementTestViewSet,
)

router = DefaultRouter()
router.register("tests", PlacementTestViewSet, basename="placement-test")
router.register("attempts", PlacementAttemptViewSet, basename="placement-attempt")
router.register("proposals", GroupProposalViewSet, basename="placement-proposal")

urlpatterns = router.urls
