from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.sales import services
from apps.sales.models import Sale
from apps.sales.serializers import RecordSaleSerializer, RefundSaleSerializer, SaleSerializer
from core.exceptions import PermissionException
from core.permissions import Role, get_role_memberships, get_user_roles
from core.viewsets import TenantSafeModelViewSet


class SaleViewSet(TenantSafeModelViewSet):
    """Book / material cash sales (#8). The till (sale:write) records a sale → money-IN
    ledger row; a refund (sale:refund) writes a compensating money-OUT row. The SALES
    rows here are branch-scoped to the seller's own till; note the underlying LedgerEntry
    rows are the centre's books and are visible centre-wide to finance roles (ledger:read
    = accountant/cashier/director) via /approvals/ledger/, by the same A-1 design as
    approval requests — not via this branch-scoped endpoint."""

    serializer_class = SaleSerializer
    resource = "sale"
    required_perms = {
        "list": "sale:read",
        "retrieve": "sale:read",
        "create": "sale:write",
        "refund": "sale:refund",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("status", "branch", "student", "payment_method")
    ordering_fields = ("created_at", "amount_uzs")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def get_queryset(self):
        qs = Sale.objects.select_related(
            "student", "student__user", "branch", "payment_method", "sold_by", "refunded_by"
        )
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        return qs.filter(branch_id__in=self._branch_ids())  # the seller's till only

    def _assert_student_in_scope(self, student) -> None:
        user = self.request.user
        if user.is_superuser or Role.DIRECTOR in get_user_roles(self.request):
            return
        if student.branch_id not in self._branch_ids():
            raise PermissionException(
                _("You can only sell to a student in your own branch."), code="branch_out_of_scope"
            )

    @extend_schema(request=RecordSaleSerializer, responses={201: SaleSerializer}, tags=["sale"])
    def create(self, request, *args, **kwargs):
        ser = RecordSaleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        student = ser.validated_data["student"]
        self._assert_student_in_scope(student)
        sale = services.record_sale(
            item=ser.validated_data["item"],
            quantity=ser.validated_data["quantity"],
            unit_price_uzs=ser.validated_data["unit_price_uzs"],
            student=student,
            payment_method_id=ser.validated_data["payment_method"],
            sold_by=request.user,
            note=ser.validated_data["note"],
        )
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=RefundSaleSerializer, responses={200: SaleSerializer}, tags=["sale"])
    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        ser = RefundSaleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sale = services.refund_sale(
            sale_id=self.get_object().pk, actor=request.user, reason=ser.validated_data["reason"]
        )
        return Response(SaleSerializer(sale).data)
