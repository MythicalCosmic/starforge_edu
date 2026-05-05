from rest_framework.routers import DefaultRouter

from .views import PaymentItemViewSet

router = DefaultRouter()
router.register(r"", PaymentItemViewSet, basename="payments")

urlpatterns = router.urls
