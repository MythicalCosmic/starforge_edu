from rest_framework.routers import DefaultRouter

from .views import StudentItemViewSet

router = DefaultRouter()
router.register(r"", StudentItemViewSet, basename="students")

urlpatterns = router.urls
