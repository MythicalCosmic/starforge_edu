"""Finance API (D3-A-9). TenantSafeModelViewSet / TenantSafeAPIView with
per-action `required_perms` (TD-5), django-filter, and `@extend_schema`."""

from __future__ import annotations

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.finance import selectors, services
from apps.finance.models import CashierShift, Discount, Expense, FeeSchedule, PaymentMethod
from apps.finance.serializers import (
    CashierShiftCloseSerializer,
    CashierShiftOpenSerializer,
    CashierShiftReadSerializer,
    DiscountSerializer,
    ExpenseCreateSerializer,
    ExpensePaySerializer,
    ExpenseReadSerializer,
    ExpenseRejectSerializer,
    FeeScheduleSerializer,
    InvoiceCreateSerializer,
    InvoiceReadSerializer,
    OutstandingSerializer,
    PaymentMethodSerializer,
    PaymentPlanCreateSerializer,
    PaymentPlanReadSerializer,
    StatementRequestSerializer,
)
from apps.org.models import Branch
from core.exceptions import PermissionException, ValidationException
from core.permissions import (
    Role,
    RolePermission,
    default_perms,
    get_user_roles,
    has_permission_code,
)
from core.utils import current_schema
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet

_STATEMENT_RESULT_TTL = 3600  # seconds the task-id -> S3 key mapping survives


class FinanceBalanceReadPermission(BasePermission):
    """Gate for the parent-scoped outstanding-balance endpoint.

    A parent/student holds `finance:read_own` (NOT `finance:read`), so the plain
    `RolePermission` single-code gate would 403 them before the view body can do
    its guardian-link row-scoping. This admits any authenticated user holding
    either `finance:read` (staff: director/accountant/cashier) OR
    `finance:read_own` (parent/student); the view body then enforces that a
    parent/student only reaches their OWN children's/own balances. Stays
    fail-closed: anonymous and unrelated roles are denied here."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        roles = get_user_roles(request)
        return has_permission_code(roles, "finance:read") or has_permission_code(roles, "finance:read_own")


class FeeScheduleViewSet(TenantSafeModelViewSet):
    serializer_class = FeeScheduleSerializer
    resource = "finance"
    queryset = FeeSchedule.objects.select_related("cohort").all()
    filterset_fields = ("is_active", "cohort", "billing_period")
    search_fields = ("name",)
    ordering_fields = ("name", "amount_uzs", "created_at")

    @extend_schema(tags=["finance"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class InvoiceViewSet(TenantSafeModelViewSet):
    """Invoices are issued through the service (numbering / FX / discounts), so
    `create` calls `issue_invoice` rather than the default serializer save. No raw
    PUT/DELETE — voiding is an explicit action."""

    serializer_class = InvoiceReadSerializer
    resource = "finance"
    required_perms = {
        **default_perms("finance"),
        "void": "finance:write",
        "payment_plan": "finance:write",
    }
    filterset_fields = ("status", "student", "cohort", "fee_schedule")
    search_fields = ("number",)
    ordering_fields = ("created_at", "due_date", "total_uzs")
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return selectors.scoped_invoices(user=self.request.user, roles=get_user_roles(self.request))

    @extend_schema(
        request=InvoiceCreateSerializer,
        responses={201: InvoiceReadSerializer, 400: OpenApiResponse(description="validation_error")},
        tags=["finance"],
        examples=[
            OpenApiExample(
                "Issue from a fee schedule",
                value={"student": 7, "fee_schedule": 3, "period": "2026-06"},
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        ser = InvoiceCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        invoice = services.issue_invoice(
            student_id=data["student"],
            fee_schedule_id=data.get("fee_schedule"),
            lines=data.get("lines"),
            period=data.get("period", ""),
            created_by=request.user,
        )
        return Response(
            InvoiceReadSerializer(self.get_queryset().get(pk=invoice.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses={200: InvoiceReadSerializer}, tags=["finance"])
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        invoice = self.get_object()
        services.void_invoice(invoice=invoice, actor=request.user)
        return Response(InvoiceReadSerializer(self.get_queryset().get(pk=invoice.pk)).data)

    @extend_schema(
        request=PaymentPlanCreateSerializer,
        responses={201: PaymentPlanReadSerializer},
        tags=["finance"],
        examples=[
            OpenApiExample(
                "Two installments",
                value={
                    "installments": [
                        {"due_date": "2026-07-05", "amount_uzs": "500000.00"},
                        {"due_date": "2026-08-05", "amount_uzs": "500000.00"},
                    ]
                },
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="payment-plan")
    def payment_plan(self, request, pk=None):
        invoice = self.get_object()
        ser = PaymentPlanCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plan = services.create_payment_plan(
            invoice=invoice,
            installments=ser.validated_data["installments"],
            created_by=request.user,
        )
        return Response(PaymentPlanReadSerializer(plan).data, status=status.HTTP_201_CREATED)


class DiscountViewSet(TenantSafeModelViewSet):
    """Discounts are GRANTED only through the Approvals engine (the `discount` KIND,
    F15-3) so every price cut carries sign-off — there is NO direct create / edit /
    delete here, which would side-step the approval gate and let anyone with
    finance:write mutate the audited discount out-of-band. Discounts are therefore
    read-only over CRUD; they can be ENDED via the explicit `deactivate` action
    (ending a benefit, lower fraud-risk than granting one) at finance:write."""

    serializer_class = DiscountSerializer
    resource = "finance"
    required_perms = {
        "list": "finance:read",
        "retrieve": "finance:read",
        "deactivate": "finance:write",
    }
    # No put / patch / delete; create is overridden below to a hard 405.
    http_method_names = ["get", "post", "head", "options"]
    queryset = Discount.objects.select_related("student__user", "approved_by").all()
    filterset_fields = ("student", "discount_type", "is_active")
    ordering_fields = ("created_at",)

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed(
            "POST",
            detail=_("Discounts are granted through an approval request, not created directly."),
        )

    @extend_schema(tags=["finance"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="End a standing discount (stops it applying to future invoices)",
        request=None,
        responses={200: DiscountSerializer},
        tags=["finance"],
    )
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        discount = self.get_object()
        if discount.is_active:
            discount.is_active = False
            discount.save(update_fields=["is_active", "updated_at"])
        return Response(DiscountSerializer(discount).data)


class PaymentMethodViewSet(TenantSafeModelViewSet):
    """Dynamic disbursement methods (cash/card/…). Managed at finance:write; any
    finance:read holder may list them (the expense pay step needs the choices)."""

    serializer_class = PaymentMethodSerializer
    resource = "finance"
    queryset = PaymentMethod.objects.all()
    filterset_fields = ("is_active",)
    search_fields = ("name", "slug")
    ordering_fields = ("name",)


class ExpenseViewSet(TenantSafeModelViewSet):
    """Expense lifecycle (F14-1): create -> approve/reject -> pay (chosen method).
    Transitions are explicit actions; no raw PUT/DELETE."""

    serializer_class = ExpenseReadSerializer
    resource = "finance"
    required_perms = {
        "list": "finance:read",
        "retrieve": "finance:read",
        "create": "finance:write",
        "approve": "finance:write",
        "reject": "finance:write",
        "pay": "finance:write",
    }
    queryset = Expense.objects.select_related(
        "branch", "payment_method", "created_by", "approved_by", "paid_by"
    ).all()
    filterset_fields = ("status", "branch", "category")
    ordering_fields = ("created_at", "amount_uzs")
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(request=ExpenseCreateSerializer, responses={201: ExpenseReadSerializer}, tags=["finance"])
    def create(self, request, *args, **kwargs):
        ser = ExpenseCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        expense = services.create_expense(
            branch=data["branch"],
            description=data["description"],
            amount_uzs=data["amount_uzs"],
            category=data.get("category", ""),
            created_by=request.user,
        )
        return Response(ExpenseReadSerializer(expense).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: ExpenseReadSerializer}, tags=["finance"])
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        expense = self.get_object()
        expense = services.approve_expense(expense_id=expense.pk, actor=request.user)
        return Response(ExpenseReadSerializer(expense).data)

    @extend_schema(request=ExpenseRejectSerializer, responses={200: ExpenseReadSerializer}, tags=["finance"])
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        expense = self.get_object()
        ser = ExpenseRejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        expense = services.reject_expense(
            expense_id=expense.pk, reason=ser.validated_data["reason"], actor=request.user
        )
        return Response(ExpenseReadSerializer(expense).data)

    @extend_schema(request=ExpensePaySerializer, responses={200: ExpenseReadSerializer}, tags=["finance"])
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        expense = self.get_object()
        ser = ExpensePaySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        expense = services.pay_expense(
            expense_id=expense.pk, payment_method_id=ser.validated_data["payment_method"], actor=request.user
        )
        return Response(ExpenseReadSerializer(expense).data)


class CashierShiftViewSet(TenantSafeModelViewSet):
    """Cashier shifts open/close + per-provider daily report.

    Per the DAY-3 D3-A-5 contract, opening/closing a shift is "finance:write
    (cashier role allowed)". The CASHIER role intentionally does NOT hold global
    finance:write (it must stay denied on fee-schedule/discount writes), so the
    shift actions gate on `payments:write` instead — the code held by exactly the
    cashier, accountant and director, i.e. the staff who run a cash drawer. Read
    actions (list/retrieve/report) stay on finance:read."""

    serializer_class = CashierShiftReadSerializer
    resource = "finance"
    required_perms = {
        "list": "finance:read",
        "retrieve": "finance:read",
        "open": "payments:write",
        "close": "payments:write",
        "report": "finance:read",
    }
    queryset = CashierShift.objects.select_related("cashier", "branch").all()
    filterset_fields = ("status", "cashier", "branch")
    ordering_fields = ("opened_at", "closed_at")
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        # 'post' stays for the open/close @actions; block raw collection-create so
        # the all-read-only serializer can't reach an INSERT with NULL cashier_id
        # (IntegrityError 500). Shifts are opened via /cashier-shifts/open/.
        raise MethodNotAllowed("POST", detail="Open a shift via /finance/cashier-shifts/open/.")

    @extend_schema(
        request=CashierShiftOpenSerializer,
        responses={201: CashierShiftReadSerializer, 409: OpenApiResponse(description="shift_already_open")},
        tags=["finance"],
    )
    @action(detail=False, methods=["post"])
    def open(self, request):
        ser = CashierShiftOpenSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        branch = get_object_or_404(Branch, pk=ser.validated_data["branch"])
        shift = services.open_cashier_shift(
            cashier=request.user,
            branch=branch,
            opening_cash_uzs=ser.validated_data["opening_cash_uzs"],
            notes=ser.validated_data["notes"],
        )
        return Response(CashierShiftReadSerializer(shift).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=CashierShiftCloseSerializer,
        responses={200: CashierShiftReadSerializer, 409: OpenApiResponse(description="shift_closed")},
        tags=["finance"],
    )
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        shift = self.get_object()
        ser = CashierShiftCloseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        shift = services.close_cashier_shift(
            shift=shift,
            closing_cash_uzs=ser.validated_data["closing_cash_uzs"],
            notes=ser.validated_data["notes"],
        )
        return Response(CashierShiftReadSerializer(shift).data)

    @extend_schema(
        responses={200: OpenApiResponse(description="per-provider totals + discrepancy")},
        tags=["finance"],
    )
    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        shift = self.get_object()
        return Response(selectors.cashier_shift_report(shift=shift))


class OutstandingBalanceView(TenantSafeAPIView):
    """GET /finance/outstanding/?student=<id> — parent-scoped balance.

    Gated by FinanceBalanceReadPermission (admits finance:read OR
    finance:read_own); the body row-scopes parents/students to their own."""

    permission_classes = [FinanceBalanceReadPermission]
    resource = "finance"
    required_perms = {"get": "finance:read"}

    @extend_schema(
        parameters=[OpenApiParameter("student", int, required=True)],
        responses={200: OutstandingSerializer},
        tags=["finance"],
    )
    def get(self, request):
        student_id = _require_int(request, "student")
        roles = get_user_roles(request)
        # A parent holds finance:read_own (not finance:read) — gate them via the
        # guardian link; finance:read holders see anyone.
        is_staff = request.user.is_superuser or has_permission_code(roles, "finance:read")
        if not is_staff:
            if Role.PARENT in roles or Role.STUDENT in roles:
                if not _can_view_balance(user=request.user, student_id=student_id, roles=roles):
                    raise PermissionException(
                        "You can only view your own children's balances.", code="forbidden"
                    )
            else:
                raise PermissionException("Insufficient finance access.", code="forbidden")

        invoices = selectors.outstanding_invoices(student_id=student_id, user=request.user, roles=roles)
        outstanding = selectors.outstanding_balance(student_id)
        payload = {
            "student": student_id,
            "outstanding_uzs": outstanding,
            "invoices": InvoiceReadSerializer(invoices, many=True).data,
        }
        return Response(payload)


def _can_view_balance(*, user, student_id: int, roles: set[str]) -> bool:
    if Role.PARENT in roles and selectors.parent_can_see_student(user=user, student_id=student_id):
        return True
    if Role.STUDENT in roles:
        from apps.students.models import StudentProfile

        return StudentProfile.objects.filter(pk=student_id, user=user).exists()
    return False


class StatementRequestView(TenantSafeAPIView):
    """POST /finance/students/{id}/statement/ -> 202 {task_id} (TD-14 async)."""

    permission_classes = [RolePermission]
    resource = "finance"
    required_perms = {"post": "finance:read"}

    @extend_schema(
        request=StatementRequestSerializer,
        responses={202: OpenApiResponse(description="{task_id}")},
        tags=["finance"],
    )
    def post(self, request, student_id: int):
        ser = StatementRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from celery_tasks.finance_tasks import generate_statement_pdf

        result = generate_statement_pdf.delay(
            int(student_id),
            locale=ser.validated_data["locale"],
            _schema_name=current_schema(),
        )
        return Response({"task_id": result.id}, status=status.HTTP_202_ACCEPTED)


class StatementResultView(TenantSafeAPIView):
    """GET /finance/statements/{task_id}/ -> {url} once the task wrote the PDF."""

    permission_classes = [RolePermission]
    resource = "finance"
    required_perms = {"get": "finance:read"}

    @extend_schema(
        responses={200: OpenApiResponse(description="{status, url?}")},
        tags=["finance"],
    )
    def get(self, request, task_id: str):
        key = cache.get(f"finance:statement:{current_schema()}:{task_id}")
        if key is None:
            return Response({"status": "pending", "url": None})
        from infrastructure.storage.s3_client import presign_download

        return Response({"status": "done", "url": presign_download(key, expires_in=600)})


def _require_int(request, name: str) -> int:
    raw = request.query_params.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationException(
            f"Query parameter '{name}' is required and must be an integer.",
            code="invalid_query_param",
            fields={name: ["This query parameter is required."]},
        ) from exc
