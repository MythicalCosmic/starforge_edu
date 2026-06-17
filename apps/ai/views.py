"""AI endpoints (D4-LA-8, TD-5 per-action perms).

- ``GET   /api/v1/ai/requests/``         ai:read   — paginated request log
- ``GET   /api/v1/ai/requests/<id>/``    ai:read
- ``GET   /api/v1/ai/budget/``           ai:read   — current budget snapshot
- ``PATCH /api/v1/ai/budget/``           ai:manage — update limits / is_enabled
- ``POST  /api/v1/ai/exam-generation/``  ai:write  — 202 {request_id}
- ``GET   /api/v1/ai/usage-report/``     ai:read   — per-feature totals

The request log is a router-registered ``ReadOnlyModelViewSet`` (list/retrieve);
budget / exam-generation / usage-report are flat ``TenantSafeAPIView``s so the
URL map matches DAY-4 exactly (``/ai/budget/`` etc., not nested under requests).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status, viewsets
from rest_framework.response import Response

from apps.ai import selectors, services
from apps.ai.filters import AIRequestFilter
from apps.ai.serializers import (
    AIRequestReadSerializer,
    BudgetReadSerializer,
    BudgetWriteSerializer,
    ExamGenerationRequestSerializer,
    ExamGenerationResponseSerializer,
    UsageReportRowSerializer,
)
from core.exceptions import ValidationException
from core.permissions import ObjectScopedPermission, RolePermission
from core.viewsets import TenantSafeAPIView, assert_tenant_context


@extend_schema(tags=["ai"])
class AIRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only AI request log. Inherits the tenant guard + role perms."""

    permission_classes = [RolePermission, ObjectScopedPermission]
    serializer_class = AIRequestReadSerializer
    resource = "ai"
    filterset_class = AIRequestFilter
    ordering_fields = ("created_at",)
    ordering = ("-created_at",)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        assert_tenant_context()

    def get_queryset(self):
        return selectors.list_requests()

    @extend_schema(
        summary="Paginated AI request log",
        description="ai:read. Filters: feature, status, created_after, created_before.",
        responses={200: AIRequestReadSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class BudgetView(TenantSafeAPIView):
    resource = "ai"
    # GET derives ai:read; PATCH is explicitly elevated to ai:manage.
    required_perms = {"get": "ai:read", "patch": "ai:manage"}

    @extend_schema(
        summary="Current AI token budget",
        responses={200: BudgetReadSerializer},
        tags=["ai"],
    )
    def get(self, request):
        budget = services._get_budget_locked()
        return Response(BudgetReadSerializer(budget).data)

    @extend_schema(
        summary="Update AI budget (director / ai:manage)",
        request=BudgetWriteSerializer,
        responses={200: BudgetReadSerializer, 403: OpenApiResponse(description="forbidden envelope")},
        tags=["ai"],
    )
    def patch(self, request):
        ser = BudgetWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        budget = services.update_budget(**ser.validated_data)
        return Response(BudgetReadSerializer(budget).data)


class ExamGenerationView(TenantSafeAPIView):
    resource = "ai"
    required_perms = {"post": "ai:write"}

    @extend_schema(
        summary="Request AI exam generation",
        description="ai:write. Gated by CenterSettings.ai_exam_generation_enabled.",
        request=ExamGenerationRequestSerializer,
        responses={
            202: ExamGenerationResponseSerializer,
            403: OpenApiResponse(description="feature_disabled envelope"),
            429: OpenApiResponse(description="ai_budget_exceeded envelope"),
        },
        examples=[
            OpenApiExample(
                "Generate a quiz",
                value={
                    "subject_id": 3,
                    "exam_type": "quiz",
                    "question_count": 10,
                    "difficulty": "medium",
                },
                request_only=True,
            )
        ],
        tags=["ai"],
    )
    def post(self, request):
        ser = ExamGenerationRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ai_request = services.request_exam_generation(requested_by=request.user, **ser.validated_data)
        return Response({"request_id": ai_request.pk}, status=status.HTTP_202_ACCEPTED)


class UsageReportView(TenantSafeAPIView):
    resource = "ai"
    required_perms = {"get": "ai:read"}

    @extend_schema(
        summary="AI usage report per feature",
        description="ai:read. Totals per feature for the given month (default: current).",
        parameters=[OpenApiParameter("month", str, description="YYYY-MM (default current month)")],
        responses={200: UsageReportRowSerializer(many=True)},
        tags=["ai"],
    )
    def get(self, request):
        start, end = _month_bounds(request.query_params.get("month"))
        rows = selectors.usage_report(start=start, end=end)
        return Response(UsageReportRowSerializer(rows, many=True).data)


def _month_bounds(month: str | None) -> tuple[date, date]:
    """Parse ``YYYY-MM`` (default: current month) into inclusive day bounds."""
    if month:
        try:
            anchor = datetime.strptime(month, "%Y-%m").date()
        except (ValueError, TypeError) as exc:
            raise ValidationException(_("month must be formatted as YYYY-MM."), code="invalid_month") from exc
    else:
        anchor = timezone.localdate()

    start = anchor.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month - timedelta(days=1)
