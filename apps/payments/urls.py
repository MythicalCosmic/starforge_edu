"""Tenant-side payments URLConf (included at /api/v1/payments/)."""

from rest_framework.routers import DefaultRouter

from apps.payments.views import PaymentViewSet, ProviderConfigViewSet

router = DefaultRouter()
router.register("provider-configs", ProviderConfigViewSet, basename="provider-configs")
router.register("", PaymentViewSet, basename="payments")

urlpatterns = router.urls
