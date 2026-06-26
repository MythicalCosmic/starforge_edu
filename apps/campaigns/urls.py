from rest_framework.routers import DefaultRouter

from apps.campaigns.views import CampaignViewSet

router = DefaultRouter()
router.register("", CampaignViewSet, basename="campaigns")

urlpatterns = router.urls
