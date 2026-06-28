from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.cards import services
from apps.cards.models import Card, CardType
from apps.cards.serializers import (
    CardSerializer,
    CardTypeSerializer,
    IssueCardSerializer,
    RevokeCardSerializer,
    ScanSerializer,
    WalletAmountSerializer,
    WalletSerializer,
    WalletTransactionSerializer,
)
from apps.students.selectors import student_profile_for
from core.exceptions import NotFoundException, PermissionException
from core.permissions import Role, RolePermission, get_role_memberships, get_user_roles, has_permission_code
from core.viewsets import TenantSafeAPIView, TenantSafeModelViewSet


class CardTypeViewSet(TenantSafeModelViewSet):
    """The center's card types (F12-1). A manager (card:write) creates + names them and
    can retire one (is_active=False); everyone with card:read can list them."""

    serializer_class = CardTypeSerializer
    resource = "card"
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_perms = {
        "list": "card:read",
        "retrieve": "card:read",
        "create": "card:write",
        "partial_update": "card:write",
    }
    queryset = CardType.objects.select_related("created_by").all()
    filterset_fields = ("is_active",)
    search_fields = ("name",)
    ordering_fields = ("name", "created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class CardViewSet(TenantSafeModelViewSet):
    """Cards issued to students (F12-1). A manager (card:write) issues a card to a student
    in their branch and can revoke it; a student reads their OWN card(s). Issuing
    generates a unique scan code; revoking makes the card scan as invalid."""

    serializer_class = CardSerializer
    resource = "card"
    http_method_names = ["get", "post", "head", "options"]
    required_perms = {
        "list": "card:read",
        "retrieve": "card:read",
        "create": "card:write",
        "revoke": "card:write",
    }
    filterset_fields = ("student", "card_type", "is_active")
    ordering_fields = ("issued_at",)

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def _is_director(self) -> bool:
        return self.request.user.is_superuser or Role.DIRECTOR in get_user_roles(self.request)

    def get_queryset(self):
        qs = Card.objects.select_related("student", "student__user", "card_type", "issued_by")
        user = self.request.user
        roles = get_user_roles(self.request)
        if self._is_director():
            return qs
        # Card STAFF — anyone who issues (card:write) OR scans (card:scan) at the door —
        # read their branch's cards; SECURITY (scan, no write) must NOT fall through to the
        # student branch and see nothing.
        if has_permission_code(roles, "card:write") or has_permission_code(roles, "card:scan"):
            return qs.filter(student__branch_id__in=self._branch_ids())
        # A student sees only their own card(s).
        profile = student_profile_for(user)
        return qs.filter(student=profile) if profile is not None else qs.none()

    def _assert_student_in_scope(self, student) -> None:
        if self._is_director():
            return
        if student.branch_id not in self._branch_ids():
            raise PermissionException(
                _("You can only issue cards to a student in your own branch."), code="branch_out_of_scope"
            )

    @extend_schema(request=IssueCardSerializer, responses={201: CardSerializer}, tags=["cards"])
    def create(self, request, *args, **kwargs):
        ser = IssueCardSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self._assert_student_in_scope(ser.validated_data["student"])
        card = services.issue_card(
            student=ser.validated_data["student"],
            card_type=ser.validated_data["card_type"],
            issued_by=request.user,
        )
        return Response(CardSerializer(card).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=RevokeCardSerializer, responses={200: CardSerializer}, tags=["cards"])
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        ser = RevokeCardSerializer(data=request.data)
        ser.is_valid(raise_exception=True)  # bounds + types `reason` (never a 500 on junk)
        card = services.revoke_card(
            card_id=self.get_object().pk, actor=request.user, reason=ser.validated_data["reason"]
        )
        return Response(CardSerializer(card).data)


class CardScanView(TenantSafeAPIView):
    """POST /api/v1/cards/scan/ — scan a card code to check a student in (card:scan, e.g.
    security/reception at the door). Returns {valid, student, ...}; an unknown code 404s,
    a revoked card returns valid=false. Every scan is logged."""

    permission_classes = [RolePermission]
    resource = "card"
    required_perms = {"post": "card:scan"}

    @extend_schema(
        request=ScanSerializer,
        responses={200: OpenApiResponse(description="{valid, student, student_name, card_type, scan_id}")},
        tags=["cards"],
    )
    def post(self, request):
        ser = ScanSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = services.scan_card(code=ser.validated_data["code"], scanned_by=request.user)
        return Response(result)


def _wallet_payload(wallet) -> dict:
    txns = wallet.transactions.all()[:50]
    return {
        "wallet": WalletSerializer(wallet).data,
        "transactions": WalletTransactionSerializer(txns, many=True).data,
    }


class WalletMeView(TenantSafeAPIView):
    """GET /api/v1/cards/wallets/me/ — the signed-in student's stored-value wallet +
    recent transactions (F12-1)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiResponse(description="{wallet, transactions}")}, tags=["cards"])
    def get(self, request):
        from apps.cards.models import Wallet

        profile = student_profile_for(request.user)
        if profile is None:
            raise NotFoundException(_("You do not have a student profile."), code="not_a_student")
        wallet, _created = Wallet.objects.get_or_create(student=profile)
        return Response(_wallet_payload(wallet))


class _StaffWalletBase(TenantSafeAPIView):
    permission_classes = [RolePermission]
    resource = "wallet"

    def _student(self, request, student_id):
        from apps.students.models import StudentProfile

        student = StudentProfile.objects.filter(pk=student_id).first()
        if student is None:
            raise NotFoundException(_("Student not found."), code="student_not_found")
        if not (request.user.is_superuser or Role.DIRECTOR in get_user_roles(request)):
            my = {m.branch_id for m in get_role_memberships(request) if m.branch_id}
            if student.branch_id not in my:
                raise PermissionException(
                    _("You can only manage a student in your own branch."), code="branch_out_of_scope"
                )
        return student


class StudentWalletView(_StaffWalletBase):
    """GET /api/v1/cards/wallets/{student_id}/ — a staff member (wallet:read) reads a
    student's wallet + recent transactions (branch-scoped)."""

    required_perms = {"get": "wallet:read"}

    @extend_schema(responses={200: OpenApiResponse(description="{wallet, transactions}")}, tags=["cards"])
    def get(self, request, student_id):
        from apps.cards.models import Wallet

        student = self._student(request, student_id)
        wallet, _created = Wallet.objects.get_or_create(student=student)
        return Response(_wallet_payload(wallet))


class WalletTopUpView(_StaffWalletBase):
    """POST /api/v1/cards/wallets/{student_id}/topup/ — load money onto the wallet
    (wallet:write, branch-scoped)."""

    required_perms = {"post": "wallet:write"}

    @extend_schema(request=WalletAmountSerializer, responses={201: WalletTransactionSerializer}, tags=["cards"])
    def post(self, request, student_id):
        student = self._student(request, student_id)
        ser = WalletAmountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        txn = services.top_up(
            student=student, amount=ser.validated_data["amount"], actor=request.user,
            note=ser.validated_data.get("note", ""),
        )
        return Response(WalletTransactionSerializer(txn).data, status=status.HTTP_201_CREATED)


class WalletSpendView(_StaffWalletBase):
    """POST /api/v1/cards/wallets/{student_id}/spend/ — charge the wallet (e.g. a canteen
    purchase). 422 insufficient_funds if the balance is too low (wallet:write)."""

    required_perms = {"post": "wallet:write"}

    @extend_schema(request=WalletAmountSerializer, responses={201: WalletTransactionSerializer}, tags=["cards"])
    def post(self, request, student_id):
        student = self._student(request, student_id)
        ser = WalletAmountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        txn = services.spend(
            student=student, amount=ser.validated_data["amount"], actor=request.user,
            note=ser.validated_data.get("note", ""),
        )
        return Response(WalletTransactionSerializer(txn).data, status=status.HTTP_201_CREATED)
