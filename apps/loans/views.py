from __future__ import annotations

from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.approvals.models import ApprovalRequest
from apps.approvals.services import KIND_LOAN
from apps.loans import services
from apps.loans.models import LoanRepayment
from apps.loans.serializers import (
    CreateLoanSerializer,
    LoanRepaymentSerializer,
    LoanSerializer,
    RecordRepaymentSerializer,
)
from core.permissions import Role, get_role_memberships, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


class LoanViewSet(TenantSafeModelViewSet):
    """Staff loans (F21-1) — the loan-specific surface over the A-1 engine: raise a
    loan, see outstanding balances, and record repayments. The approve/disburse
    decision itself lives in the unified approvals queue (/api/v1/approvals/)."""

    serializer_class = LoanSerializer
    resource = "loan"
    required_perms = {
        "list": "loan:read",
        "retrieve": "loan:read",
        "create": "loan:write",
        "repay": "loan:collect",
        "repayments": "loan:read",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("status", "branch")
    ordering_fields = ("created_at", "amount_uzs")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def get_queryset(self):
        qs = (
            ApprovalRequest.objects.filter(kind=KIND_LOAN)
            .select_related("branch", "requested_by", "decided_by", "disbursed_by", "ledger_entry")
            .annotate(
                repaid_uzs_annotated=Coalesce(
                    Sum("loan_repayments__amount_uzs"),
                    Value(Decimal("0")),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            )
            .order_by("-created_at")  # annotate's GROUP BY can drop Meta.ordering
        )
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        if has_permission_code(roles, "loan:collect"):
            # Finance handlers see their branches' loans (plus centre-wide ones).
            my = self._branch_ids()
            return qs.filter(Q(branch_id__in=my) | Q(branch__isnull=True))
        # A borrower sees only their own loans (raised by or for them).
        return qs.filter(Q(requested_by=user) | Q(payload__borrower_id=user.id))

    @extend_schema(request=CreateLoanSerializer, responses={201: LoanSerializer}, tags=["loan"])
    def create(self, request, *args, **kwargs):
        ser = CreateLoanSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        loan = services.request_loan(
            requested_by=request.user,
            amount_uzs=ser.validated_data["amount_uzs"],
            title=ser.validated_data["title"],
            description=ser.validated_data["description"],
            branch=ser.validated_data.get("branch"),
            borrower=ser.validated_data.get("borrower"),
        )
        return Response(
            LoanSerializer(self.get_queryset().get(pk=loan.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=RecordRepaymentSerializer, responses={201: LoanSerializer}, tags=["loan"])
    @action(detail=True, methods=["post"])
    def repay(self, request, pk=None):
        loan = self.get_object()
        ser = RecordRepaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.record_repayment(
            loan_id=loan.pk,
            amount_uzs=ser.validated_data["amount_uzs"],
            payment_method_id=ser.validated_data["payment_method"],
            actor=request.user,
            note=ser.validated_data["note"],
        )
        return Response(
            LoanSerializer(self.get_queryset().get(pk=loan.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(responses={200: LoanRepaymentSerializer(many=True)}, tags=["loan"])
    @action(detail=True, methods=["get"])
    def repayments(self, request, pk=None):
        loan = self.get_object()
        rows = LoanRepayment.objects.filter(loan=loan).select_related(
            "payment_method", "branch", "recorded_by"
        )
        return Response(LoanRepaymentSerializer(rows, many=True).data)
