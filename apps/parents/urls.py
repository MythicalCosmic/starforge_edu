from rest_framework.routers import DefaultRouter

from .views import GuardianViewSet, ParentProfileViewSet

router = DefaultRouter()
router.register(r"guardians", GuardianViewSet, basename="guardians")
router.register(r"", ParentProfileViewSet, basename="parents")

urlpatterns = router.urls
