"""Audit URLConf (D3-D-4, D3-D-7).

`export/` is declared BEFORE the router so it is never shadowed by the `{pk}`
detail route. The router yields GET-only `audit/` (list) + `audit/{id}/`
(retrieve); all write verbs 405 (read-only viewset).
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.audit.views import AuditExportView, AuditLogViewSet

router = DefaultRouter()
router.register(r"", AuditLogViewSet, basename="audit")

urlpatterns = [
    path("export/", AuditExportView.as_view(), name="audit-export"),
    *router.urls,
]
