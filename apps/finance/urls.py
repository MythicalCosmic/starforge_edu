from rest_framework.routers import DefaultRouter

from .views import FinanceItemViewSet

router = DefaultRouter()
router.register(r"", FinanceItemViewSet, basename="finance")

urlpatterns = router.urls
