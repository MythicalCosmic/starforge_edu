from rest_framework.routers import DefaultRouter

from .views import ReportItemViewSet

router = DefaultRouter()
router.register(r"", ReportItemViewSet, basename="reports")

urlpatterns = router.urls
