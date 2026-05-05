from rest_framework.routers import DefaultRouter

from .views import ParentItemViewSet

router = DefaultRouter()
router.register(r"", ParentItemViewSet, basename="parents")

urlpatterns = router.urls
