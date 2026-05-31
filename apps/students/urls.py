from rest_framework.routers import DefaultRouter

from .views import StudentProfileViewSet

router = DefaultRouter()
router.register(r"", StudentProfileViewSet, basename="students")

urlpatterns = router.urls
