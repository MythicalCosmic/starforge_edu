from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.org.models import Branch
from apps.procurement.models import PurchaseOrder, PurchaseOrderItem


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    line_total_uzs = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderItem
        fields = ("id", "description", "quantity", "unit_price_uzs", "line_total_uzs")
        read_only_fields = fields

    def get_line_total_uzs(self, obj) -> str:
        return str(obj.line_total_uzs.quantize(Decimal("0.01")))


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    status = serializers.CharField(source="request.status", read_only=True)
    amount_uzs = serializers.DecimalField(
        source="request.amount_uzs", max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "request",
            "supplier",
            "branch",
            "status",
            "amount_uzs",
            "items",
            "created_by",
            "created_at",
        )
        read_only_fields = fields


class _CreatePOItemSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    unit_price_uzs = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0"))


class CreatePurchaseOrderSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    supplier = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    items = _CreatePOItemSerializer(many=True, allow_empty=False)
