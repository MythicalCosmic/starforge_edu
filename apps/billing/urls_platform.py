"""Control-center subscription URLs (D4-LE-3) — PUBLIC schema, staff-only.

Mounted in config/urls_public.py under `api/v1/platform/` (a flat
`/platform/subscriptions/` surface for the control center, distinct from the
legacy `/platform/billing/subscriptions/{center_id}/` lookup-by-center
viewset). See integration_needed for the include line.
"""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.billing.views import PlatformSubscriptionViewSet

router = DefaultRouter()
router.register("subscriptions", PlatformSubscriptionViewSet, basename="platform-subscriptions")

urlpatterns = router.urls
