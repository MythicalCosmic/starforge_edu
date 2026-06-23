from rest_framework.routers import DefaultRouter

from apps.approvals.views import ApprovalRequestViewSet, LedgerEntryViewSet

router = DefaultRouter()
router.register("requests", ApprovalRequestViewSet, basename="approval-request")
router.register("ledger", LedgerEntryViewSet, basename="ledger-entry")

urlpatterns = router.urls
