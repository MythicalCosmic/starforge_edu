"""Payments serializers (read/write split; credentials write-only — TD-11)."""

from __future__ import annotations

from rest_framework import serializers

from apps.payments.models import FiscalReceipt, Payment, PaymentAttempt, ProviderConfig


class ProviderConfigSerializer(serializers.ModelSerializer):
    """Credential fields are WRITE-ONLY — never echoed back (TD-11/CODE-GUIDE §11)."""

    class Meta:
        model = ProviderConfig
        fields = (
            "id",
            "provider",
            "is_active",
            "click_service_id",
            "click_merchant_id",
            "click_secret_key",
            "payme_merchant_id",
            "payme_key",
            "payme_test_key",
            "uzum_merchant_id",
            "uzum_api_key",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")
        extra_kwargs = {
            "click_secret_key": {"write_only": True, "required": False},
            "payme_key": {"write_only": True, "required": False},
            "payme_test_key": {"write_only": True, "required": False},
            "uzum_api_key": {"write_only": True, "required": False},
        }


class FiscalReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalReceipt
        fields = ("id", "status", "fiscal_sign", "qr_url", "attempts", "submitted_at", "confirmed_at")


class PaymentAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAttempt
        fields = ("id", "attempt_no", "error_code", "created_at")


class PaymentReadSerializer(serializers.ModelSerializer):
    fiscal_receipt = FiscalReceiptSerializer(read_only=True)
    attempts = PaymentAttemptSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "provider",
            "amount_uzs",
            "currency",
            "status",
            "provider_txn_id",
            "provider_state",
            "account_ref",
            "allocation_status",
            "cashier_shift",
            "payer",
            "paid_at",
            "fiscal_receipt",
            "attempts",
            "created_at",
            "updated_at",
        )


class PaymentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            "id",
            "provider",
            "amount_uzs",
            "status",
            "provider_txn_id",
            "account_ref",
            "allocation_status",
            "paid_at",
            "created_at",
        )


class CheckoutSerializer(serializers.Serializer):
    invoice = serializers.IntegerField()
    provider = serializers.ChoiceField(choices=[("click", "click"), ("payme", "payme"), ("uzum", "uzum")])


class AllocationItemSerializer(serializers.Serializer):
    invoice = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class AllocateSerializer(serializers.Serializer):
    allocations = AllocationItemSerializer(many=True)


class RefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CashPaymentSerializer(serializers.Serializer):
    """Cash intake at the drawer: an invoice id and an optional amount (defaults
    to the invoice total). The payment is stamped with the cashier's open shift."""

    invoice = serializers.IntegerField()
    amount_uzs = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
