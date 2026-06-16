"""Public-schema webhook URLConf (D3-B-5, TD-6).

Included by ``config/urls_public.py`` at ``api/v1/webhooks/`` so the final shape
is ``POST /api/v1/webhooks/<provider>/<center_slug>/``. Lives on the PUBLIC
URLConf, not the tenant one — providers push to the apex host; the view resolves
the tenant from ``center_slug`` and enters ``schema_context`` (see webhook_views).
"""

from __future__ import annotations

from django.urls import path

from apps.payments.webhook_views import ClickWebhookView, PaymeWebhookView, UzumWebhookView

urlpatterns = [
    path("click/<slug:center_slug>/", ClickWebhookView.as_view(), name="webhook-click"),
    path("payme/<slug:center_slug>/", PaymeWebhookView.as_view(), name="webhook-payme"),
    path("uzum/<slug:center_slug>/", UzumWebhookView.as_view(), name="webhook-uzum"),
]
