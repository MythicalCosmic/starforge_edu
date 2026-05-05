from rest_framework.routers import DefaultRouter

from .views import PrintingItemViewSet

router = DefaultRouter()
router.register(r"", PrintingItemViewSet, basename="printing")

urlpatterns = router.urls
