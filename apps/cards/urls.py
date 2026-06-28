from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.cards.views import (
    CardScanView,
    CardTypeViewSet,
    CardViewSet,
    StudentWalletView,
    WalletMeView,
    WalletSpendView,
    WalletTopUpView,
)

router = DefaultRouter()
router.register("types", CardTypeViewSet, basename="card-type")
router.register("", CardViewSet, basename="card")

urlpatterns = [
    # Specific paths before the catch-all "" card route (and "me" before "<student_id>").
    path("scan/", CardScanView.as_view(), name="card-scan"),
    path("wallets/me/", WalletMeView.as_view(), name="wallet-me"),
    path("wallets/<int:student_id>/", StudentWalletView.as_view(), name="wallet-detail"),
    path("wallets/<int:student_id>/topup/", WalletTopUpView.as_view(), name="wallet-topup"),
    path("wallets/<int:student_id>/spend/", WalletSpendView.as_view(), name="wallet-spend"),
    *router.urls,
]
