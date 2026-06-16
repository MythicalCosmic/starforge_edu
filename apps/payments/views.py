"""Payments tenant-side views (D3-B-7..11). Thin: wire perms + serializer +
service/selector. Per-action ``required_perms`` (TD-5); ``@extend_schema`` on
every endpoint (DoD #7)."""

from __future__ import annotations

from datetime import date

from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.payments import selectors, services
from apps.payments.models import Payment, ProviderConfig
from apps.payments.serializers import (
    AllocateSerializer,
    CashPaymentSerializer,
    CheckoutSerializer,
    PaymentListSerializer,
    PaymentReadSerializer,
    ProviderConfigSerializer,
    RefundSerializer,
)
from core.exceptions import ValidationException
from core.permissions import default_perms
from core.utils import current_schema, stable_hash
from core.viewsets import TenantSafeModelViewSet
from infrastructure.storage.s3_client import presign_download


class ProviderConfigViewSet(TenantSafeModelViewSet):
    """Provider credentials CRUD — director/accountant only (payments:write).
    Credential fields are write-only; reads never echo secrets."""

    queryset = ProviderConfig.objects.all().order_by("provider")
    serializer_class = ProviderConfigSerializer
    resource = "payments"
    required_perms = {**default_perms("payments")}  # list/retrieve → payments:read; writes → payments:write
    filterset_fields = ("provider", "is_active")
    ordering_fields = ("provider",)


class PaymentViewSet(TenantSafeModelViewSet):
    # Explicit empty default for drf-spectacular schema introspection; the real
    # rows come from the user-scoped get_queryset (mirrors the content viewsets).
    queryset = Payment.objects.none()
    resource = "payments"
    required_perms = {
        "list": "payments:read",
        "retrieve": "payments:read",
        "checkout": "payments:write",
        "cash": "payments:write",
        "allocate": "payments:write",
        "refund": "payments:write",
        "reconciliation": "payments:read",
        "receipt": "payments:read",
    }
    filterset_fields = ("provider", "status", "allocation_status")
    ordering_fields = ("created_at", "paid_at", "amount_uzs")
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return selectors.payments_qs()

    def get_serializer_class(self):
        if self.action == "list":
            return PaymentListSerializer
        return PaymentReadSerializer

    @extend_schema(
        summary="Create a checkout for an invoice",
        request=CheckoutSerializer,
        responses={201: OpenApiResponse(description="{payment_id, provider, redirect_url|rpc_payload}")},
        tags=["payments"],
        examples=[OpenApiExample("Payme checkout", value={"invoice": 12, "provider": "payme"})],
    )
    @action(detail=False, methods=["post"])
    def checkout(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        # Idempotency-Key header (TASKS §16) or a derived stable key per (invoice, provider, user).
        idem = request.headers.get("Idempotency-Key") or stable_hash(
            f"checkout:{current_schema()}:{ser.validated_data['invoice']}:{ser.validated_data['provider']}:{request.user.pk}"
        )
        result = services.create_checkout(
            invoice_id=ser.validated_data["invoice"],
            provider=ser.validated_data["provider"],
            idempotency_key=idem,
            payer=request.user,
        )
        return Response(result, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Record a cash payment at the cashier drawer",
        description=(
            "Creates a COMPLETED cash Payment stamped with the cashier's open "
            "shift and auto-allocates it against the invoice. The cashier must "
            "have an open shift (409 otherwise)."
        ),
        request=CashPaymentSerializer,
        responses={201: PaymentReadSerializer},
        tags=["payments"],
        examples=[OpenApiExample("Cash for invoice", value={"invoice": 12, "amount_uzs": "150000.00"})],
    )
    @action(detail=False, methods=["post"])
    def cash(self, request):
        ser = CashPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payment = services.create_cash_payment(
            invoice_id=ser.validated_data["invoice"],
            cashier=request.user,
            amount_uzs=ser.validated_data.get("amount_uzs"),
        )
        return Response(PaymentReadSerializer(payment).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Manually allocate a completed payment across invoices",
        request=AllocateSerializer,
        responses={200: PaymentReadSerializer},
        tags=["payments"],
    )
    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        ser = AllocateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payment = services.allocate_manual(payment_id=int(pk), allocations=ser.validated_data["allocations"])
        return Response(PaymentReadSerializer(payment).data)

    @extend_schema(
        summary="Refund a completed payment",
        request=RefundSerializer,
        responses={200: PaymentReadSerializer},
        tags=["payments"],
    )
    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        ser = RefundSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payment = services.refund_payment(
            payment_id=int(pk),
            amount_uzs=ser.validated_data.get("amount"),
            reason=ser.validated_data.get("reason", ""),
        )
        return Response(PaymentReadSerializer(payment).data)

    @extend_schema(
        summary="Daily reconciliation: payments vs allocated totals",
        parameters=[OpenApiParameter("date", str, description="YYYY-MM-DD (default today)")],
        responses={200: OpenApiResponse(description="reconciliation report")},
        tags=["payments"],
    )
    @action(detail=False, methods=["get"])
    def reconciliation(self, request):
        raw = request.query_params.get("date")
        if raw:
            try:
                on = date.fromisoformat(raw)
            except ValueError as exc:
                raise ValidationException("date must be YYYY-MM-DD.", fields={"date": ["invalid"]}) from exc
        else:
            on = timezone.localdate()
        return Response(selectors.reconciliation(on=on))

    @extend_schema(
        summary="Signed URL to a payment's fiscal receipt PDF",
        description="Returns a signed URL when the PDF exists, else enqueues its render and returns 202.",
        responses={
            200: OpenApiResponse(description="{url}"),
            202: OpenApiResponse(description="{status: 'generating'}"),
            404: OpenApiResponse(description="no fiscal receipt yet"),
        },
        tags=["payments"],
    )
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        payment = self.get_object()
        receipt = getattr(payment, "fiscal_receipt", None)
        if receipt is None:
            return Response(
                {"error": {"code": "not_found", "detail": "No fiscal receipt for this payment yet."}},
                status=404,
            )
        key = (receipt.payload or {}).get("pdf_key")
        if key:
            return Response({"url": presign_download(key, expires_in=600)})
        services.enqueue_receipt_pdf(payment.pk, current_schema())
        return Response({"status": "generating"}, status=status.HTTP_202_ACCEPTED)
