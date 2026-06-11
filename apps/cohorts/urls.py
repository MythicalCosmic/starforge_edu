from rest_framework.routers import DefaultRouter

from .views import CohortViewSet

router = DefaultRouter()
router.register(r"", CohortViewSet, basename="cohorts")

urlpatterns = router.urls
