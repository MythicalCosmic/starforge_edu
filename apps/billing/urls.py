"""Billing platform URLs — included in config/urls_public.py under
`api/v1/platform/billing/` (PUBLIC schema only)."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.billing.views import (
    AiUsageChargeView,
    CheckoutView,
    PlanViewSet,
    SubscriptionViewSet,
    UsageView,
)

router = DefaultRouter()
router.register("plans", PlanViewSet, basename="billing-plans")
router.register("subscriptions", SubscriptionViewSet, basename="billing-subscriptions")

urlpatterns = [
    path("usage/", UsageView.as_view(), name="billing-usage"),
    path("ai-charges/", AiUsageChargeView.as_view(), name="billing-ai-charges"),
    path("checkout/", CheckoutView.as_view(), name="billing-checkout"),
    *router.urls,
]
