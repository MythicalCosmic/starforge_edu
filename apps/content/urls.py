from rest_framework.routers import DefaultRouter

from .views import ContentItemViewSet

router = DefaultRouter()
router.register(r"", ContentItemViewSet, basename="content")

urlpatterns = router.urls
