from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.sales.models import Sale
from apps.students.models import StudentProfile


class SaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sale
        fields = (
            "id",
            "item",
            "quantity",
            "unit_price_uzs",
            "amount_uzs",
            "student",
            "branch",
            "payment_method",
            "status",
            "ledger_entry",
            "refund_ledger_entry",
            "sold_by",
            "refunded_by",
            "refunded_at",
            "refund_reason",
            "note",
            "created_at",
        )
        read_only_fields = fields


class RecordSaleSerializer(serializers.Serializer):
    item = serializers.CharField(max_length=200)
    # Capped so an absurd quantity is a clean 400, not a NUMERIC/int4 overflow 500.
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000, default=1)
    unit_price_uzs = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    payment_method = serializers.IntegerField()
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RefundSaleSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
