"""Tenant-schema URLConf — served when a request maps to a tenant subdomain."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

import core.schema  # noqa: F401 — registers the OpenAPI auth extension (TD-1)

api_v1_patterns = [
    path("auth/", include("apps.auth.urls")),
    path("users/", include("apps.users.urls")),
    path("org/", include("apps.org.urls")),
    path("students/", include("apps.students.urls")),
    path("parents/", include("apps.parents.urls")),
    path("teachers/", include("apps.teachers.urls")),
    path("cohorts/", include("apps.cohorts.urls")),
    path("schedule/", include("apps.schedule.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("academics/", include("apps.academics.urls")),
    path("assignments/", include("apps.assignments.urls")),
    path("content/", include("apps.content.urls")),
    path("printing/", include("apps.printing.urls")),
    path("finance/", include("apps.finance.urls")),
    path("payments/", include("apps.payments.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("ai/", include("apps.ai.urls")),
    path("audit/", include("apps.audit.urls")),
    path("reports/", include("apps.reports.urls")),
    path("approvals/", include("apps.approvals.urls")),
    path("rulebook/", include("apps.compliance.urls")),
    path("access/", include("apps.access.urls")),
    path("forms/", include("apps.forms.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("messaging/", include("apps.messaging.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_v1_patterns, "v1"))),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
