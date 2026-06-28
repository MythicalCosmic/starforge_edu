from rest_framework.routers import DefaultRouter

from apps.campaigns.views import CampaignViewSet, DoNotContactViewSet, MessageTemplateViewSet

router = DefaultRouter()
# Specific routes before the catch-all "" campaign route.
router.register("do-not-contact", DoNotContactViewSet, basename="do-not-contact")
router.register("templates", MessageTemplateViewSet, basename="message-template")
router.register("", CampaignViewSet, basename="campaigns")

urlpatterns = router.urls
