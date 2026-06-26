from rest_framework.routers import DefaultRouter

from apps.loans.views import LoanViewSet

router = DefaultRouter()
router.register("", LoanViewSet, basename="loans")

urlpatterns = router.urls
