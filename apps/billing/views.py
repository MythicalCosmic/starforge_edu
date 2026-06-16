"""Billing platform API (D3-E-8) — PUBLIC schema, platform-staff only.

These views run on the public schema (mounted in config/urls_public.py under
/api/v1/platform/billing/). They are PLAIN DRF viewsets/APIViews with
`permission_classes = [IsAdminUser]` — NOT `TenantSafeModelViewSet`, whose
`initial()` raises TenantContextMissing on the public schema. Platform staff
exist as public-schema users per TD-3.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing import selectors, services
from apps.billing.models import Plan, Subscription
from apps.billing.serializers import (
    CheckoutSerializer,
    PlanSerializer,
    SubscriptionSerializer,
    SubscriptionUpdateSerializer,
    UsageSnapshotSerializer,
)
from core.exceptions import ValidationException


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/v1/platform/billing/plans/ — the plan catalog."""

    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ("is_active",)
    ordering_fields = ("price_uzs", "code")
    search_fields = ("code", "name")

    @extend_schema(summary="List subscription plans", tags=["platform-billing"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class SubscriptionViewSet(viewsets.GenericViewSet):
    """GET/PATCH /api/v1/platform/billing/subscriptions/{center_id}/.

    Lookup is by `center_id` (a Center has exactly one subscription).
    """

    queryset = Subscription.objects.none()  # router/schema introspection only
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAdminUser]
    lookup_url_kwarg = "center_id"
    # \d+ so a non-numeric center id 404s at routing instead of ValueError → 500.
    lookup_value_regex = r"\d+"

    def _get_subscription(self, center_id: int) -> Subscription:
        sub = selectors.subscription_for_center(center_id=center_id)
        if sub is None:
            from core.exceptions import NotFoundException

            raise NotFoundException()
        return sub

    @extend_schema(
        summary="Retrieve a Center's subscription",
        responses={200: SubscriptionSerializer},
        tags=["platform-billing"],
    )
    def retrieve(self, request, center_id=None):
        sub = self._get_subscription(int(center_id))
        return Response(SubscriptionSerializer(sub).data)

    @extend_schema(
        summary="Change plan or set status (active|suspended)",
        request=SubscriptionUpdateSerializer,
        responses={200: SubscriptionSerializer},
        tags=["platform-billing"],
        examples=[OpenApiExample("Suspend", value={"status": "suspended"})],
    )
    def partial_update(self, request, center_id=None):
        ser = SubscriptionUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sub = services.change_subscription(
            center_id=int(center_id),
            plan_code=ser.validated_data.get("plan_code"),
            status=ser.validated_data.get("status"),
        )
        return Response(SubscriptionSerializer(sub).data)


class UsageView(APIView):
    """GET /api/v1/platform/billing/usage/?center=<id> — usage snapshots."""

    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List usage snapshots for a center",
        responses={200: UsageSnapshotSerializer(many=True)},
        tags=["platform-billing"],
    )
    def get(self, request):
        center_id = request.query_params.get("center")
        if not center_id:
            raise ValidationException("Query param `center` is required.", code="validation_error")
        try:
            center_id_int = int(center_id)
        except (TypeError, ValueError):
            raise ValidationException("`center` must be an integer.", code="validation_error") from None
        qs = selectors.usage_for_center(center_id=center_id_int)
        return Response(UsageSnapshotSerializer(qs, many=True).data)


class CheckoutView(APIView):
    """POST /api/v1/platform/billing/checkout/ — mock platform subscription pay."""

    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Pay a platform subscription (mock) — extends period +30d, sets active",
        request=CheckoutSerializer,
        responses={
            200: SubscriptionSerializer,
            400: OpenApiResponse(description="validation_error / platform_payment_failed envelope"),
        },
        tags=["platform-billing"],
        examples=[OpenApiExample("Pay via Payme", value={"center": 1, "provider": "payme"})],
    )
    def post(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sub = services.process_platform_checkout(
            center_id=ser.validated_data["center"],
            provider=ser.validated_data["provider"],
        )
        return Response(SubscriptionSerializer(sub).data, status=status.HTTP_200_OK)
