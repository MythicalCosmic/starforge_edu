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
    # D4-LE-3: flat control-center subscription management (by subscription id).
    path("api/v1/platform/", include("apps.billing.urls_platform")),
    # TD-6: provider webhooks land on the public schema and resolve the tenant
    # by <center_slug> in the path, then verify the provider signature.
    path("api/v1/webhooks/", include("apps.payments.webhook_urls")),
]

# Serve /static/ (platform admin CSS/JS) from the app when DEBUG — see config/urls.py.
from django.conf import settings  # noqa: E402

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()

# Backend API: Django's own error responses (unmatched URL, uncaught 500, CSRF
# 403, suspicious-operation 400) return the JSON {"error": {...}} envelope.
handler400 = "core.middleware.json_400"
handler403 = "core.middleware.json_403"
handler404 = "core.middleware.json_404"
handler500 = "core.middleware.json_500"
