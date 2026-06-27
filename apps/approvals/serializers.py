from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.approvals.models import ApprovalRequest, LedgerEntry
from apps.org.models import Branch

# Documented request kinds (configured instances of the engine). "other" is the
# escape hatch; richer per-center kinds arrive with the dynamic config (A-2).
REQUEST_KINDS = (
    "expense",
    "loan",
    "procurement",
    "discount",
    "fine",
    "payment_delay",
    "salary_prep",
    "event_split",
    "book_cash",
    "reward",
    "other",
)


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = (
            "id",
            "direction",
            "entry_type",
            "amount_uzs",
            "branch",
            "party_label",
            "payment_method",
            "source_kind",
            "source_id",
            "note",
            "created_by",
            "created_at",
        )
        read_only_fields = fields


class ApprovalRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalRequest
        fields = (
            "id",
            "kind",
            "branch",
            "requested_by",
            "title",
            "description",
            "amount_uzs",
            "payload",
            "status",
            "decided_by",
            "decided_at",
            "decision_note",
            "disbursed_by",
            "disbursed_at",
            "payment_method",
            "ledger_entry",
            "created_at",
        )
        read_only_fields = fields


class ApprovalRequestCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=REQUEST_KINDS)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    amount_uzs = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0.01")
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    payload = serializers.JSONField(required=False, default=dict)


class ApprovalDecisionSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class ApprovalDisburseSerializer(serializers.Serializer):
    payment_method = serializers.IntegerField()
    direction = serializers.ChoiceField(
        choices=(LedgerEntry.Direction.IN, LedgerEntry.Direction.OUT),
        required=False,
        default=LedgerEntry.Direction.OUT,
    )
    entry_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    party_label = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
