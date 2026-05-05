from rest_framework.routers import DefaultRouter

from .views import CohortItemViewSet

router = DefaultRouter()
router.register(r"", CohortItemViewSet, basename="cohorts")

urlpatterns = router.urls
