from rest_framework.routers import DefaultRouter

from apps.messaging.views import ThreadViewSet

router = DefaultRouter()
router.register("threads", ThreadViewSet, basename="threads")

urlpatterns = router.urls
