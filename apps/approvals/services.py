"""Approvals + Ledger engine services.

State machine: PENDING -> APPROVED | REJECTED | CANCELLED; APPROVED -> DISBURSED
(money-moving kinds) writes an immutable LedgerEntry. Every transition is locked
with select_for_update so concurrent approve/disburse can't double-act.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.approvals.models import ApprovalRequest, LedgerEntry
from core.exceptions import NotFoundException, UnprocessableEntity, ValidationException
from core.permissions import roles_with_permission

# Kinds whose payload is validated at creation time and which carry an
# on-approval side-effect (see _apply_approval_effect).
KIND_DISCOUNT = "discount"


def _notify(*, event_type: str, recipient_id: int | None, req: ApprovalRequest) -> None:
    """Best-effort in-app notification on an approval transition (never breaks the
    money transition — failures are swallowed/logged inside dispatch)."""
    if recipient_id is None:
        return
    from apps.notifications.services import dispatch

    dispatch(
        event_type=event_type,
        recipient_id=recipient_id,
        context={
            "kind": req.kind,
            "title": req.title,
            "amount_uzs": str(req.amount_uzs) if req.amount_uzs is not None else "",
            "request_id": req.pk,
        },
    )


def _disburser_ids(req: ApprovalRequest) -> list[int]:
    """Active users who may disburse — scoped to the request's branch when set."""
    from apps.users.models import RoleMembership

    qs = RoleMembership.objects.filter(
        role__in=roles_with_permission("approvals:disburse"), revoked_at__isnull=True
    )
    if req.branch_id:
        qs = qs.filter(branch_id=req.branch_id)
    return list(qs.values_list("user_id", flat=True).distinct())


def _validate_discount_payload(payload: dict) -> dict:
    """Validate + normalize a discount-request payload at creation time, so a
    malformed discount never enters the approval queue (a clean 400, not a 500
    when someone later approves it). Shape:

        {student_id, discount_type?, (percent | fixed_amount_uzs), valid_from?, valid_until?}

    Exactly one of percent / fixed_amount_uzs must be set (mirrors the Discount
    model's XOR CheckConstraint). Numbers are stored as strings to keep the JSON
    payload exact (no float drift) and dates as ISO strings.
    """
    from apps.finance.models import Discount
    from apps.students.models import StudentProfile

    student_id = payload.get("student_id")
    if not isinstance(student_id, int) or not StudentProfile.objects.filter(pk=student_id).exists():
        raise ValidationException(
            _("A discount request needs a valid student_id in its payload."),
            code="discount_student_required",
            fields={"payload": ["student_id"]},
        )

    percent = payload.get("percent")
    fixed = payload.get("fixed_amount_uzs")
    if (percent is None) == (fixed is None):
        raise ValidationException(
            _("Set exactly one of payload.percent or payload.fixed_amount_uzs."),
            code="discount_amount_xor",
        )

    dtype = payload.get("discount_type", Discount.DiscountType.MANUAL)
    if dtype not in Discount.DiscountType.values:
        raise ValidationException(_("Unknown discount_type."), code="discount_type_invalid")

    clean: dict = {"student_id": student_id, "discount_type": dtype}
    if percent is not None:
        try:
            pv = Decimal(str(percent))
        except (InvalidOperation, ValueError):
            raise ValidationException(
                _("percent must be a number."), code="discount_percent_invalid"
            ) from None
        if not (Decimal("0") < pv <= Decimal("100")):
            raise ValidationException(_("percent must be between 0 and 100."), code="discount_percent_range")
        clean["percent"] = str(pv)
    else:
        try:
            fv = Decimal(str(fixed))
        except (InvalidOperation, ValueError):
            raise ValidationException(
                _("fixed_amount_uzs must be a number."), code="discount_fixed_invalid"
            ) from None
        if fv <= 0:
            raise ValidationException(_("fixed_amount_uzs must be positive."), code="discount_fixed_range")
        clean["fixed_amount_uzs"] = str(fv)

    for key in ("valid_from", "valid_until"):
        raw = payload.get(key)
        if raw:
            try:
                clean[key] = date.fromisoformat(str(raw)).isoformat()
            except ValueError:
                raise ValidationException(
                    _("%(key)s must be an ISO date (YYYY-MM-DD).") % {"key": key},
                    code="discount_date_invalid",
                ) from None
    return clean


@transaction.atomic
def create_request(
    *,
    kind: str,
    title: str,
    requested_by=None,
    amount_uzs: Decimal | None = None,
    description: str = "",
    branch=None,
    payload: dict | None = None,
) -> ApprovalRequest:
    payload = payload or {}
    if kind == KIND_DISCOUNT:
        # A discount is decision-only (the Discount it grants is the effect, not a
        # cash payout) — it never disburses, so drop any amount the caller passed.
        payload = _validate_discount_payload(payload)
        amount_uzs = None
    return ApprovalRequest.objects.create(
        kind=kind,
        title=title,
        requested_by=requested_by,
        amount_uzs=amount_uzs,
        description=description,
        branch=branch,
        payload=payload,
    )


def _apply_discount_effect(req: ApprovalRequest, actor) -> None:
    """On approval, a discount request materializes a standing Discount for the
    student — which finance then auto-applies as a negative invoice line at the
    next issue (apps.finance._active_discounts). Runs inside approve()'s
    transaction, so a failed effect rolls the approval back. The created discount
    id is stamped into the payload as the audit link."""
    from apps.finance.models import Discount
    from apps.students.models import StudentProfile

    p = dict(req.payload or {})
    if p.get("discount_id"):  # defensive: status gate already prevents re-approval
        return
    student_id = p.get("student_id")
    if not student_id or not StudentProfile.objects.filter(pk=student_id).exists():
        raise UnprocessableEntity(
            _("The discount's student no longer exists."), code="discount_student_missing"
        )
    discount = Discount.objects.create(
        student_id=student_id,
        discount_type=p.get("discount_type", Discount.DiscountType.MANUAL),
        percent=Decimal(p["percent"]) if p.get("percent") is not None else None,
        fixed_amount_uzs=Decimal(p["fixed_amount_uzs"]) if p.get("fixed_amount_uzs") is not None else None,
        valid_from=p.get("valid_from") or None,
        valid_until=p.get("valid_until") or None,
        approved_by=actor,
    )
    req.payload = {**p, "discount_id": discount.pk}


def _apply_approval_effect(req: ApprovalRequest, actor) -> None:
    """Dispatch the kind-specific side-effect that fires the instant a request is
    APPROVED. Money-moving kinds (loan/expense/...) act at disburse time instead;
    decision kinds with an effect (discount) act here."""
    if req.kind == KIND_DISCOUNT:
        _apply_discount_effect(req, actor)


def _locked(request_id: int) -> ApprovalRequest:
    req = ApprovalRequest.objects.select_for_update().filter(pk=request_id).first()
    if req is None:
        raise NotFoundException(_("Approval request not found."), code="approval_not_found")
    return req


@transaction.atomic
def approve(*, request_id: int, actor=None, note: str = "") -> ApprovalRequest:
    req = _locked(request_id)
    if req.status != ApprovalRequest.Status.PENDING:
        raise UnprocessableEntity(_("Only a pending request can be approved."), code="approval_not_pending")
    req.status = ApprovalRequest.Status.APPROVED
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.decision_note = note
    # Side-effect (e.g. discount -> standing Discount) runs in this same transaction
    # and may stamp req.payload, so persist payload alongside the decision fields.
    _apply_approval_effect(req, actor)
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "payload", "updated_at"])
    _notify(event_type="approval.approved", recipient_id=req.requested_by_id, req=req)
    if req.amount_uzs is not None:
        # Tell whoever can pay it out that money is ready to be readied (PRODUCT_VISION
        # "cashier auto-notified to ready the money").
        for uid in _disburser_ids(req):
            _notify(event_type="approval.awaiting_disbursement", recipient_id=uid, req=req)
    return req


@transaction.atomic
def reject(*, request_id: int, actor=None, note: str = "") -> ApprovalRequest:
    req = _locked(request_id)
    if req.status not in (ApprovalRequest.Status.PENDING, ApprovalRequest.Status.APPROVED):
        raise UnprocessableEntity(
            _("This request can no longer be rejected."), code="approval_not_rejectable"
        )
    req.status = ApprovalRequest.Status.REJECTED
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.decision_note = note
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    _notify(event_type="approval.rejected", recipient_id=req.requested_by_id, req=req)
    return req


@transaction.atomic
def cancel(*, request_id: int, actor=None) -> ApprovalRequest:
    """Requester withdraws a still-pending request (ownership enforced by the view)."""
    req = _locked(request_id)
    if req.status != ApprovalRequest.Status.PENDING:
        raise UnprocessableEntity(
            _("Only a pending request can be cancelled."), code="approval_not_cancellable"
        )
    req.status = ApprovalRequest.Status.CANCELLED
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    return req


@transaction.atomic
def disburse(
    *,
    request_id: int,
    payment_method_id: int,
    actor=None,
    direction: str = LedgerEntry.Direction.OUT,
    entry_type: str = "",
    party_label: str = "",
) -> ApprovalRequest:
    """Pay out an APPROVED, amount-bearing request: writes one immutable LedgerEntry
    and links it. Idempotency is guaranteed by the status gate (a DISBURSED request
    can't be disbursed again)."""
    from apps.finance.models import PaymentMethod

    req = _locked(request_id)
    if req.status != ApprovalRequest.Status.APPROVED:
        raise UnprocessableEntity(
            _("Only an approved request can be disbursed."), code="approval_not_approved"
        )
    if req.amount_uzs is None:
        raise UnprocessableEntity(_("This request has no amount to disburse."), code="approval_no_amount")
    method = PaymentMethod.objects.filter(pk=payment_method_id, is_active=True).first()
    if method is None:
        raise UnprocessableEntity(_("Unknown or inactive payment method."), code="payment_method_invalid")

    entry = LedgerEntry.objects.create(
        direction=direction,
        entry_type=entry_type or req.kind,
        amount_uzs=req.amount_uzs,
        branch=req.branch,
        party_label=party_label or (req.requested_by.get_full_name() if req.requested_by else ""),
        payment_method=method,
        source_kind="approval_request",
        source_id=req.pk,
        note=req.title[:255],
        created_by=actor,
    )
    req.status = ApprovalRequest.Status.DISBURSED
    req.disbursed_by = actor
    req.disbursed_at = timezone.now()
    req.payment_method = method
    req.ledger_entry = entry
    req.save(
        update_fields=[
            "status",
            "disbursed_by",
            "disbursed_at",
            "payment_method",
            "ledger_entry",
            "updated_at",
        ]
    )
    _notify(event_type="approval.disbursed", recipient_id=req.requested_by_id, req=req)
    return req
