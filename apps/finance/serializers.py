"""Finance serializers — read/write split; no `fields = "__all__"`."""

from __future__ import annotations

from decimal import Decimal

from django.utils.text import slugify
from rest_framework import serializers

from apps.finance.models import (
    CashierShift,
    Discount,
    Expense,
    FeeSchedule,
    Invoice,
    InvoiceLine,
    PaymentAllocation,
    PaymentMethod,
    PaymentPlan,
    PaymentPlanInstallment,
)
from apps.org.models import Branch


class FeeScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeSchedule
        fields = (
            "id",
            "name",
            "cohort",
            "amount_uzs",
            "billing_period",
            "due_day_of_month",
            "is_active",
            "created_at",
        )
        read_only_fields = ("created_at",)


class InvoiceLineReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = (
            "id",
            "description",
            "line_type",
            "quantity",
            "unit_price_uzs",
            "amount_uzs",
        )
        read_only_fields = fields


class PaymentAllocationReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAllocation
        fields = ("id", "payment_id", "amount_uzs", "created_at")
        read_only_fields = fields


class InvoiceReadSerializer(serializers.ModelSerializer):
    lines = InvoiceLineReadSerializer(many=True, read_only=True)
    allocations = PaymentAllocationReadSerializer(many=True, read_only=True)
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)

    class Meta:
        model = Invoice
        fields = (
            "id",
            "number",
            "student",
            "student_name",
            "cohort",
            "fee_schedule",
            "period",
            "status",
            "issue_date",
            "due_date",
            "currency",
            "total_uzs",
            "fx_rate_usd",
            "fx_source",
            "total_usd",
            "created_by",
            "created_at",
            "lines",
            "allocations",
        )
        read_only_fields = fields


class InvoiceLineWriteSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255)
    line_type = serializers.ChoiceField(
        choices=InvoiceLine.LineType.choices, default=InvoiceLine.LineType.OTHER
    )
    quantity = serializers.DecimalField(max_digits=8, decimal_places=2, default=Decimal("1"))
    unit_price_uzs = serializers.DecimalField(max_digits=18, decimal_places=2)


class InvoiceCreateSerializer(serializers.Serializer):
    """POST /invoices/ — issue from a fee schedule and/or explicit lines."""

    student = serializers.IntegerField()
    fee_schedule = serializers.IntegerField(required=False, allow_null=True)
    period = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    lines = InvoiceLineWriteSerializer(many=True, required=False)


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = (
            "id",
            "student",
            "discount_type",
            "percent",
            "fixed_amount_uzs",
            "valid_from",
            "valid_until",
            "approved_by",
            "is_active",
            "created_at",
        )
        read_only_fields = ("created_at",)

    def validate(self, attrs):
        percent = attrs.get("percent")
        fixed = attrs.get("fixed_amount_uzs")
        if (percent is None) == (fixed is None):
            raise serializers.ValidationError(
                {"percent": ["Set exactly one of percent or fixed_amount_uzs."]}
            )
        return attrs


class InstallmentWriteSerializer(serializers.Serializer):
    due_date = serializers.DateField()
    amount_uzs = serializers.DecimalField(max_digits=18, decimal_places=2)


class PaymentPlanCreateSerializer(serializers.Serializer):
    installments = InstallmentWriteSerializer(many=True)


class InstallmentReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentPlanInstallment
        fields = ("id", "due_date", "amount_uzs", "status")
        read_only_fields = fields


class PaymentPlanReadSerializer(serializers.ModelSerializer):
    installments = InstallmentReadSerializer(many=True, read_only=True)

    class Meta:
        model = PaymentPlan
        fields = ("id", "invoice", "installments", "created_at")
        read_only_fields = fields


class OutstandingSerializer(serializers.Serializer):
    student = serializers.IntegerField()
    outstanding_uzs = serializers.DecimalField(max_digits=18, decimal_places=2)
    invoices = InvoiceReadSerializer(many=True)


class CashierShiftReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashierShift
        fields = (
            "id",
            "cashier",
            "branch",
            "status",
            "opened_at",
            "closed_at",
            "opening_cash_uzs",
            "closing_cash_uzs",
            "discrepancy_uzs",
            "notes",
        )
        read_only_fields = (
            "id",
            "cashier",
            "status",
            "opened_at",
            "closed_at",
            "closing_cash_uzs",
            "discrepancy_uzs",
        )


class CashierShiftOpenSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    opening_cash_uzs = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0")
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CashierShiftCloseSerializer(serializers.Serializer):
    closing_cash_uzs = serializers.DecimalField(max_digits=18, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class StatementRequestSerializer(serializers.Serializer):
    locale = serializers.ChoiceField(choices=("uz", "ru", "en"), required=False, default="en")


# --------------------------------------------------------------------------- #
# Expenses + payment methods (F14)
# --------------------------------------------------------------------------- #
class PaymentMethodSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False)

    class Meta:
        model = PaymentMethod
        fields = ("id", "name", "slug", "is_active")

    def validate(self, attrs):
        if not attrs.get("slug") and attrs.get("name"):
            attrs["slug"] = slugify(attrs["name"])[:64]
        return attrs


class ExpenseReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = (
            "id",
            "branch",
            "category",
            "description",
            "amount_uzs",
            "status",
            "payment_method",
            "reject_reason",
            "created_by",
            "approved_by",
            "paid_by",
            "created_at",
            "approved_at",
            "paid_at",
        )
        read_only_fields = fields


class ExpenseCreateSerializer(serializers.Serializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(archived_at__isnull=True))
    description = serializers.CharField(max_length=255)
    amount_uzs = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    category = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")


class ExpensePaySerializer(serializers.Serializer):
    payment_method = serializers.IntegerField()


class ExpenseRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
