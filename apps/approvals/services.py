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
from core.exceptions import (
    NotFoundException,
    PermissionException,
    UnprocessableEntity,
    ValidationException,
)
from core.permissions import roles_with_permission

# Kinds whose payload is validated at creation time and which carry an
# on-approval side-effect (see _apply_approval_effect).
KIND_DISCOUNT = "discount"
KIND_PAYMENT_DELAY = "payment_delay"
# A money-moving kind (acts at disburse, not approve) that additionally needs a
# validated borrower in its payload — see _validate_loan_payload (F21-1).
KIND_LOAN = "loan"

# Money/percent columns are NUMERIC(_, 2); normalize payload values to that scale.
_TWO_PLACES = Decimal("0.01")


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
        # Quantize to the Discount column's scale (NUMERIC(5,2)) at the gate, so the
        # audited payload always equals the discount that actually bills the student
        # (Postgres would otherwise silently round on insert -> audit divergence).
        clean["percent"] = str(pv.quantize(_TWO_PLACES))
    else:
        try:
            fv = Decimal(str(fixed))
        except (InvalidOperation, ValueError):
            raise ValidationException(
                _("fixed_amount_uzs must be a number."), code="discount_fixed_invalid"
            ) from None
        if fv <= 0:
            raise ValidationException(_("fixed_amount_uzs must be positive."), code="discount_fixed_range")
        # NUMERIC(18,2): at most 16 integer digits. Reject the overflow at the gate
        # as a clean 400 rather than letting it surface as a DB 500 at approve time.
        if fv >= Decimal("1e16"):
            raise ValidationException(_("fixed_amount_uzs is too large."), code="discount_fixed_range")
        clean["fixed_amount_uzs"] = str(fv.quantize(_TWO_PLACES))

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


def _validate_payment_delay_payload(payload: dict) -> dict:
    """Validate + normalize a payment-delay payload at creation time. Shape:

        {invoice_id, new_due_date}

    The target must be an OPEN invoice with a due date, and new_due_date must be
    strictly later than the current one (you can only delay, never advance/backdate).
    Re-checked again at approve time, since the invoice may move in between.
    """
    from apps.finance.models import Invoice
    from apps.finance.services import OPEN_STATUSES

    invoice_id = payload.get("invoice_id")
    invoice = Invoice.objects.filter(pk=invoice_id).first() if isinstance(invoice_id, int) else None
    if invoice is None:
        raise ValidationException(
            _("A payment-delay request needs a valid invoice_id in its payload."),
            code="payment_delay_invoice_required",
            fields={"payload": ["invoice_id"]},
        )
    if invoice.status not in OPEN_STATUSES:
        raise ValidationException(
            _("Only an open invoice's payment can be delayed."), code="payment_delay_invoice_not_open"
        )
    if invoice.due_date is None:
        raise ValidationException(
            _("This invoice has no due date to extend."), code="payment_delay_no_due_date"
        )

    try:
        new_due = date.fromisoformat(str(payload.get("new_due_date")))
    except ValueError:
        raise ValidationException(
            _("new_due_date must be an ISO date (YYYY-MM-DD)."), code="payment_delay_date_invalid"
        ) from None
    if new_due <= invoice.due_date:
        raise ValidationException(
            _("A payment delay can only move the due date later."), code="payment_delay_not_later"
        )
    if new_due < timezone.now().date():
        # A delay into the past is meaningless: it would leave the bill overdue with
        # no observable grace. Require it to land today or later.
        raise ValidationException(
            _("A payment delay must move the due date to today or later."),
            code="payment_delay_in_past",
        )
    return {"invoice_id": invoice_id, "new_due_date": new_due.isoformat()}


def _validate_loan_payload(payload: dict) -> dict:
    """Validate a staff-loan payload at creation time. Shape: {borrower_id}.

    The borrower must be an active STAFF member (never a student/parent — a "staff
    loan" pays staff, mirroring the F17-1 rewards recipient guard). Their display
    name is stamped into the payload as `party_label` (truncated to the ledger
    column width), so both the disbursement (money OUT) and every repayment (money
    IN) name the BORROWER on the ledger — not whoever keyed the request — which is
    the "who actually owes the centre" audit line.
    """
    from apps.users.models import User
    from core.permissions import Role

    staff_roles = tuple(r for r in Role.ALL if r not in (Role.STUDENT, Role.PARENT))
    borrower_id = payload.get("borrower_id")
    borrower = (
        User.objects.filter(
            pk=borrower_id,
            is_active=True,
            # Positive role condition on the join → only users WITH a live staff
            # membership match (avoids the LEFT-JOIN isnull trap matching everyone).
            role_memberships__revoked_at__isnull=True,
            role_memberships__role__in=staff_roles,
        )
        .distinct()
        .first()
        if isinstance(borrower_id, int)
        else None
    )
    if borrower is None:
        raise ValidationException(
            _("A loan request needs a valid staff borrower_id in its payload."),
            code="loan_borrower_required",
            fields={"payload": ["borrower_id"]},
        )
    return {"borrower_id": borrower_id, "party_label": (borrower.get_full_name() or borrower.username)[:200]}


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
    elif kind == KIND_PAYMENT_DELAY:
        # Also decision-only: the effect is moving a due date, not paying money out.
        payload = _validate_payment_delay_payload(payload)
        amount_uzs = None
    elif kind == KIND_LOAN:
        # Money-moving: a loan must carry the amount to be paid out, and a borrower.
        if amount_uzs is None:
            raise ValidationException(_("A loan request must have an amount."), code="loan_amount_required")
        payload = {**(payload or {}), **_validate_loan_payload(payload)}
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


def _apply_payment_delay_effect(req: ApprovalRequest, actor) -> None:
    """On approval, a payment-delay request pushes its target invoice's due date
    via the finance service (which re-validates + un-overdues atomically). The
    prior due date/status are snapshotted (so a later rejection can restore them)
    and the applied date/status are stamped into the payload as the audit trail."""
    from apps.finance.models import Invoice
    from apps.finance.services import extend_invoice_due_date

    p = dict(req.payload or {})
    before = Invoice.objects.filter(pk=p["invoice_id"]).only("due_date", "status").first()
    previous_due = before.due_date.isoformat() if before and before.due_date else None
    previous_status = before.status if before else None
    invoice = extend_invoice_due_date(
        invoice_id=p["invoice_id"],
        new_due_date=date.fromisoformat(p["new_due_date"]),
        actor=actor,
    )
    req.payload = {
        **p,
        "previous_due_date": previous_due,
        "previous_status": previous_status,
        "applied_due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "invoice_status": invoice.status,
    }


def _apply_approval_effect(req: ApprovalRequest, actor) -> None:
    """Dispatch the kind-specific side-effect that fires the instant a request is
    APPROVED. Money-moving kinds (loan/expense/...) act at disburse time instead;
    decision kinds with an effect (discount, payment_delay) act here."""
    if req.kind == KIND_DISCOUNT:
        _apply_discount_effect(req, actor)
    elif req.kind == KIND_PAYMENT_DELAY:
        _apply_payment_delay_effect(req, actor)


def _reverse_discount_effect(req: ApprovalRequest) -> None:
    """Deactivate the granted Discount so it stops auto-applying — a rejected price
    cut must not keep cutting prices."""
    from apps.finance.models import Discount

    p = dict(req.payload or {})
    discount_id = p.get("discount_id")
    if discount_id:
        Discount.objects.filter(pk=discount_id).update(is_active=False)
        req.payload = {**p, "effect_reversed": True}


def _reverse_payment_delay_effect(req: ApprovalRequest, actor) -> None:
    """Put the invoice's due date back to its pre-extension value (snapshotted at
    approve time), re-flagging OVERDUE if appropriate."""
    from apps.finance.services import restore_invoice_due_date

    p = dict(req.payload or {})
    invoice_id = p.get("invoice_id")
    if invoice_id and "previous_due_date" in p:
        prev = p["previous_due_date"]
        restore_invoice_due_date(
            invoice_id=invoice_id,
            due_date=date.fromisoformat(prev) if prev else None,
            actor=actor,
        )
        req.payload = {**p, "effect_reversed": True}


def _reverse_approval_effect(req: ApprovalRequest, actor) -> None:
    """Compensate the on-approval side-effect when an already-APPROVED request is
    overturned (rejected). Money-moving kinds need no reversal here — they only act
    at disburse. Runs inside reject()'s transaction so the undo is atomic."""
    if req.kind == KIND_DISCOUNT:
        _reverse_discount_effect(req)
    elif req.kind == KIND_PAYMENT_DELAY:
        _reverse_payment_delay_effect(req, actor)


def _locked(request_id: int) -> ApprovalRequest:
    req = ApprovalRequest.objects.select_for_update().filter(pk=request_id).first()
    if req is None:
        raise NotFoundException(_("Approval request not found."), code="approval_not_found")
    return req


def _assert_not_self_approval(req: ApprovalRequest, actor) -> None:
    """Segregation of duties / maker-checker: the person who raised a request may
    never sign it off (anti-fraud DNA — "no untracked favours"). Enforced in the
    service so every caller is covered, not just the view. Superusers are exempt."""
    if actor is None or getattr(actor, "is_superuser", False):
        return
    if req.requested_by_id and req.requested_by_id == getattr(actor, "id", None):
        raise PermissionException(_("You cannot approve your own request."), code="self_approval")


def _assert_not_loan_self_dealing(req: ApprovalRequest, actor) -> None:
    """Segregation of duties extends to the BENEFICIARY, not just the maker: a loan's
    borrower may neither approve nor disburse their own loan. Without this, a
    colleague keys a loan naming the borrower, and the borrower (if they hold
    approve/disburse rights) signs off the payout to themselves — the requester
    self-approval block alone misses it. Superusers are exempt."""
    if actor is None or getattr(actor, "is_superuser", False):
        return
    if req.kind == KIND_LOAN and req.payload.get("borrower_id") == getattr(actor, "id", None):
        raise PermissionException(
            _("You cannot approve or disburse your own loan."), code="loan_self_dealing"
        )


@transaction.atomic
def approve(*, request_id: int, actor=None, note: str = "") -> ApprovalRequest:
    req = _locked(request_id)
    if req.status != ApprovalRequest.Status.PENDING:
        raise UnprocessableEntity(_("Only a pending request can be approved."), code="approval_not_pending")
    _assert_not_self_approval(req, actor)
    _assert_not_loan_self_dealing(req, actor)
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
    was_approved = req.status == ApprovalRequest.Status.APPROVED
    req.status = ApprovalRequest.Status.REJECTED
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.decision_note = note
    if was_approved:
        # Overturning an approval whose effect already fired (discount / payment_delay)
        # must undo that effect, atomically, or a "rejected" decision still bites.
        _reverse_approval_effect(req, actor)
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "payload", "updated_at"])
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
    _assert_not_loan_self_dealing(req, actor)
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
        # Explicit label wins; else a payload-supplied payee (e.g. a reward's
        # recipient, who is NOT the requester); else fall back to the requester.
        # Truncated to the column width (varchar(200)) — a long full name must not
        # surface as a DB 500.
        party_label=(
            party_label
            or req.payload.get("party_label")
            or (req.requested_by.get_full_name() if req.requested_by else "")
        )[:200],
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
