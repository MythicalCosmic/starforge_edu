from rest_framework.routers import DefaultRouter

from .views import TeacherItemViewSet

router = DefaultRouter()
router.register(r"", TeacherItemViewSet, basename="teachers")

urlpatterns = router.urls
