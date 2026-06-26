from rest_framework.routers import DefaultRouter

from apps.covers.views import CoverRequestViewSet

router = DefaultRouter()
router.register("", CoverRequestViewSet, basename="covers")

urlpatterns = router.urls
