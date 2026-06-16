"""Audit API (D3-D-4, D3-D-7).

Append-only and read-only by construction:
- `AuditLogViewSet` is a DRF `ReadOnlyModelViewSet` (list + retrieve only). It
  declares `http_method_names = ["get", "head", "options"]`, so PUT/PATCH/DELETE
  and POST resolve to **405 Method Not Allowed** — there is no mutation path to
  an immutable model.
- `TimelinePagination` (cursor on `-created_at`) keeps the timeline stable under
  concurrent inserts.
- The CSV export streams the same filtered selector; a result set over
  `MAX_EXPORT_ROWS` is rejected 400 ("narrow your filters") and the export
  itself is audited via `audit_log(action="export")`.
"""

from __future__ import annotations

import csv
from datetime import datetime

import django_filters
from django.http import StreamingHttpResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.exceptions import MethodNotAllowed

from apps.audit import selectors
from apps.audit.models import AuditLog
from apps.audit.serializers import AuditLogSerializer
from apps.audit.services import audit_log
from core.exceptions import ValidationException
from core.pagination import TimelinePagination
from core.permissions import RolePermission
from core.utils import client_ip, user_agent
from core.viewsets import TenantSafeAPIView, assert_tenant_context

# A CSV stream beyond this size is a misuse of the export endpoint; force the
# caller to narrow filters rather than dump the entire trail.
MAX_EXPORT_ROWS = 50_000


class AuditLogFilter(django_filters.FilterSet):
    actor = django_filters.NumberFilter(field_name="actor_id")
    action = django_filters.CharFilter(field_name="action")
    resource_type = django_filters.CharFilter(field_name="resource_type")
    resource_id = django_filters.CharFilter(field_name="resource_id")
    ts_from = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    ts_to = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = AuditLog
        fields = ("actor", "action", "resource_type", "resource_id", "ts_from", "ts_to")


@extend_schema(tags=["audit"])
class AuditLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """GET /api/v1/audit/ (cursor-paginated) + GET /api/v1/audit/{id}/.

    Read-only: any write verb returns 405. `audit:read` for all actions.
    """

    serializer_class = AuditLogSerializer
    # RolePermission is NOT the DRF default (settings default is IsAuthenticated),
    # so it must be declared explicitly here — otherwise `resource = "audit"`
    # would never be enforced and any authenticated role could read the trail.
    permission_classes = [RolePermission]
    resource = "audit"
    pagination_class = TimelinePagination
    filterset_class = AuditLogFilter
    ordering_fields = ("created_at",)
    # No mutating verbs: PUT/PATCH/DELETE/POST -> 405 against the immutable model.
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        return selectors.audit_logs()

    def initial(self, request, *args, **kwargs):
        # 405 MUST win over 403 for the immutable audit trail (D3-F-7).
        #
        # DRF's APIView.dispatch() runs initial() -> check_permissions() BEFORE
        # the http_method_names 405 check, so a write verb (PUT/PATCH/DELETE/
        # POST) would otherwise hit RolePermission first. RolePermission has no
        # verb mapping for those raw method names (action is None on an unmapped
        # route), so it fails closed with 403 — masking the fact that the verb
        # is simply not allowed. Reject the disallowed verb here, before any
        # permission/tenant work, so the attacker sees 405 (not 403/401).
        if request.method and request.method.lower() not in self.http_method_names:
            raise MethodNotAllowed(request.method)
        # Read-only viewset (not TenantSafeModelViewSet) — assert the tenant
        # guard explicitly so the audit trail is never served on the public
        # schema (symmetry with AuditExportView).
        super().initial(request, *args, **kwargs)
        assert_tenant_context()


class AuditExportView(TenantSafeAPIView):
    """GET /api/v1/audit/export/ — streaming CSV of the filtered trail.

    Shares the selector filters with the list endpoint. A result set over
    `MAX_EXPORT_ROWS` is refused with 400 `validation_error`. The export action
    is itself recorded as an `export` audit row (D3-D-7).
    """

    permission_classes = [RolePermission]
    resource = "audit"
    required_perms = {"get": "audit:read"}

    @extend_schema(
        summary="Export the audit trail as CSV (same filters as the list)",
        parameters=[
            OpenApiParameter("actor", int, required=False),
            OpenApiParameter("action", str, required=False),
            OpenApiParameter("resource_type", str, required=False),
            OpenApiParameter("resource_id", str, required=False),
            OpenApiParameter("ts_from", str, required=False),
            OpenApiParameter("ts_to", str, required=False),
        ],
        responses={
            200: OpenApiResponse(description="text/csv stream"),
            400: OpenApiResponse(description="validation_error: too many rows / bad ts param"),
            403: OpenApiResponse(description="forbidden envelope"),
        },
        tags=["audit"],
    )
    def get(self, request):
        qs = selectors.filtered_audit_logs(
            actor=_int_param(request, "actor"),
            action=request.query_params.get("action") or None,
            resource_type=request.query_params.get("resource_type") or None,
            resource_id=request.query_params.get("resource_id") or None,
            ts_from=_dt_param(request, "ts_from"),
            ts_to=_dt_param(request, "ts_to"),
        )
        total = qs.count()
        if total > MAX_EXPORT_ROWS:
            raise ValidationException(
                "Too many rows to export; narrow your filters.",
                code="validation_error",
                fields={"rows": [f"{total} rows match (max {MAX_EXPORT_ROWS})."]},
            )

        audit_log(
            actor=request.user,
            action=AuditLog.Action.EXPORT,
            resource_type="audit.AuditLog",
            after={"rows": total, "filters": dict(request.query_params)},
            ip=client_ip(request) or None,
            user_agent=user_agent(request),
        )

        response = StreamingHttpResponse(_csv_rows(qs), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="audit_log.csv"'
        return response

    def initial(self, request, *args, **kwargs):
        # TenantSafeAPIView guards the public schema; keep the explicit check so
        # the export path is symmetric with the viewset.
        super().initial(request, *args, **kwargs)
        assert_tenant_context()


_CSV_HEADER = [
    "id",
    "created_at",
    "actor_id",
    "actor_repr",
    "action",
    "resource_type",
    "resource_id",
    "ip",
    "user_agent",
]


def _csv_rows(qs):
    writer = csv.writer(_Echo())
    yield writer.writerow(_CSV_HEADER)
    for row in qs.iterator():
        yield writer.writerow(
            [
                row.id,
                row.created_at.isoformat(),
                row.actor_id or "",
                row.actor_repr,
                row.action,
                row.resource_type,
                row.resource_id,
                row.ip or "",
                row.user_agent,
            ]
        )


class _Echo:
    """Write-only file-like object that returns each row for StreamingHttpResponse."""

    def write(self, value: str) -> str:
        return value


def _int_param(request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationException(
            f"Query parameter '{name}' must be an integer.",
            code="validation_error",
            fields={name: ["Enter a valid integer."]},
        ) from exc


def _dt_param(request, name: str) -> datetime | None:
    raw = request.query_params.get(name)
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        raise ValidationException(
            f"Query parameter '{name}' must be a valid ISO 8601 datetime.",
            code="validation_error",
            fields={name: ["Enter a valid ISO 8601 datetime."]},
        )
    return parsed
