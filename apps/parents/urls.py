from rest_framework.routers import DefaultRouter

from .views import GuardianViewSet, ParentViewSet, PickupAuthorizationViewSet

router = DefaultRouter()
# Specific routes before the catch-all "" parent route.
router.register(r"guardians", GuardianViewSet, basename="guardian")
router.register(r"pickups", PickupAuthorizationViewSet, basename="pickup")
router.register(r"", ParentViewSet, basename="parents")

urlpatterns = router.urls
