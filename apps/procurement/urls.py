from rest_framework.routers import DefaultRouter

from apps.procurement.views import PurchaseOrderViewSet

router = DefaultRouter()
router.register("", PurchaseOrderViewSet, basename="procurement")

urlpatterns = router.urls
