"""Audit read-side selectors (D3-D-4).

Read-only, eager-loaded, append-only timeline. `select_related("actor")` keeps
the list endpoint at a fixed query budget regardless of row count. Filtering by
actor / action / resource_type / resource_id / ts range is applied here so the
viewset and the CSV export share one scoping path.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import QuerySet

from apps.audit.models import AuditLog


def audit_logs() -> QuerySet[AuditLog]:
    """Base queryset for the audit timeline (newest first, actor pre-joined)."""
    return AuditLog.objects.select_related("actor").order_by("-created_at", "-id")


def filtered_audit_logs(
    *,
    actor: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ts_from: datetime | None = None,
    ts_to: datetime | None = None,
) -> QuerySet[AuditLog]:
    """The selector behind both the API list and the CSV export — one scoping
    path, so a filter that narrows the export also narrows the timeline."""
    qs = audit_logs()
    if actor is not None:
        qs = qs.filter(actor_id=actor)
    if action:
        qs = qs.filter(action=action)
    if resource_type:
        qs = qs.filter(resource_type=resource_type)
    if resource_id:
        qs = qs.filter(resource_id=str(resource_id))
    if ts_from is not None:
        qs = qs.filter(created_at__gte=ts_from)
    if ts_to is not None:
        qs = qs.filter(created_at__lte=ts_to)
    return qs
