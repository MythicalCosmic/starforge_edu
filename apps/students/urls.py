from rest_framework.routers import DefaultRouter

from .views import StudentViewSet

router = DefaultRouter()
router.register(r"", StudentViewSet, basename="students")

urlpatterns = router.urls
