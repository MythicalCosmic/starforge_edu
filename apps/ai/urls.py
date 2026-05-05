from rest_framework.routers import DefaultRouter

from .views import AiItemViewSet

router = DefaultRouter()
router.register(r"", AiItemViewSet, basename="ai_app")

urlpatterns = router.urls
