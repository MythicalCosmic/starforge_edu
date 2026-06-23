from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.finance.views import (
    CashierShiftViewSet,
    DiscountViewSet,
    ExpenseViewSet,
    FeeScheduleViewSet,
    InvoiceViewSet,
    OutstandingBalanceView,
    PaymentMethodViewSet,
    StatementRequestView,
    StatementResultView,
)

router = DefaultRouter()
router.register("fee-schedules", FeeScheduleViewSet, basename="finance-fee-schedules")
router.register("invoices", InvoiceViewSet, basename="finance-invoices")
router.register("discounts", DiscountViewSet, basename="finance-discounts")
router.register("cashier-shifts", CashierShiftViewSet, basename="finance-cashier-shifts")
router.register("payment-methods", PaymentMethodViewSet, basename="finance-payment-methods")
router.register("expenses", ExpenseViewSet, basename="finance-expenses")

urlpatterns = [
    path("outstanding/", OutstandingBalanceView.as_view(), name="finance-outstanding"),
    path(
        "students/<int:student_id>/statement/",
        StatementRequestView.as_view(),
        name="finance-statement-request",
    ),
    path(
        "statements/<str:task_id>/",
        StatementResultView.as_view(),
        name="finance-statement-result",
    ),
    *router.urls,
]
