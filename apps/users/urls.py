from rest_framework.routers import DefaultRouter

from .views import DeviceViewSet, UserViewSet

router = DefaultRouter()
router.register(r"devices", DeviceViewSet, basename="device")
router.register(r"", UserViewSet, basename="user")

urlpatterns = router.urls
