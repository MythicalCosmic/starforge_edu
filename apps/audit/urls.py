from rest_framework.routers import DefaultRouter

from .views import AuditItemViewSet

router = DefaultRouter()
router.register(r"", AuditItemViewSet, basename="audit")

urlpatterns = router.urls
