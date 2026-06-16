"""Public-schema URLConf — served on the bare apex domain.

Only platform-level concerns live here: the platform admin and the
endpoint(s) used to create new tenants. Everything tenant-specific
must go through the tenant URLConf in config/urls.py.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/platform/", include("apps.tenancy.urls")),
    # TD-8: platform billing API (plans/subscriptions/usage/checkout), staff-only.
    path("api/v1/platform/billing/", include("apps.billing.urls")),
    # TD-6: provider webhooks land on the public schema and resolve the tenant
    # by <center_slug> in the path, then verify the provider signature.
    path("api/v1/webhooks/", include("apps.payments.webhook_urls")),
]
