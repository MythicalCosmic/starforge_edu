from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.approvals.models import ApprovalRequest
from apps.loans.models import LoanRepayment
from apps.loans.services import repaid_total
from apps.org.models import Branch
from apps.users.models import User
from core.permissions import Role

# A staff loan goes to staff — never a student/parent (mirrors F17-1 rewards).
_STAFF_ROLES = tuple(r for r in Role.ALL if r not in (Role.STUDENT, Role.PARENT))


class LoanRepaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanRepayment
        fields = (
            "id",
            "loan",
            "amount_uzs",
            "branch",
            "payment_method",
            "ledger_entry",
            "recorded_by",
            "note",
            "created_at",
        )
        read_only_fields = fields


class LoanSerializer(serializers.ModelSerializer):
    """A loan is an ApprovalRequest (kind="loan") plus its repayment standing."""

    repaid_uzs = serializers.SerializerMethodField()
    outstanding_uzs = serializers.SerializerMethodField()
    settled = serializers.SerializerMethodField()

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
            "disbursed_by",
            "disbursed_at",
            "ledger_entry",
            "repaid_uzs",
            "outstanding_uzs",
            "settled",
            "created_at",
        )
        read_only_fields = fields

    def _repaid(self, obj) -> Decimal:
        # Prefer the queryset annotation (no N+1 on list); fall back to a query.
        annotated = getattr(obj, "repaid_uzs_annotated", None)
        return annotated if annotated is not None else repaid_total(obj)

    def get_repaid_uzs(self, obj) -> str:
        # Quantize to the money scale so the contract is always 2dp ("0.00", not "0").
        return str(self._repaid(obj).quantize(Decimal("0.01")))

    def get_outstanding_uzs(self, obj) -> str | None:
        if obj.status != ApprovalRequest.Status.DISBURSED or obj.amount_uzs is None:
            return None
        return str(obj.amount_uzs - self._repaid(obj))

    def get_settled(self, obj) -> bool:
        if obj.status != ApprovalRequest.Status.DISBURSED or obj.amount_uzs is None:
            return False
        return obj.amount_uzs - self._repaid(obj) <= 0


class CreateLoanSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    amount_uzs = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    description = serializers.CharField(required=False, allow_blank=True, default="")
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    # Optional: a manager raising a loan for another staff member. Defaults to the
    # requester (borrowing for themselves). Restricted to active STAFF.
    borrower = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            is_active=True,
            role_memberships__revoked_at__isnull=True,
            role_memberships__role__in=_STAFF_ROLES,
        ).distinct(),
        required=False,
        allow_null=True,
    )


class RecordRepaymentSerializer(serializers.Serializer):
    amount_uzs = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    payment_method = serializers.IntegerField()
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
