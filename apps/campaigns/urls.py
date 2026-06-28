from rest_framework.routers import DefaultRouter

from apps.campaigns.views import CampaignViewSet, DoNotContactViewSet

router = DefaultRouter()
# Specific route before the catch-all "" campaign route.
router.register("do-not-contact", DoNotContactViewSet, basename="do-not-contact")
router.register("", CampaignViewSet, basename="campaigns")

urlpatterns = router.urls
