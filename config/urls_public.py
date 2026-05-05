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
]
