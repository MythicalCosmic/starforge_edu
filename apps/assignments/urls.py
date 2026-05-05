from rest_framework.routers import DefaultRouter

from .views import AssignmentItemViewSet

router = DefaultRouter()
router.register(r"", AssignmentItemViewSet, basename="assignments")

urlpatterns = router.urls
