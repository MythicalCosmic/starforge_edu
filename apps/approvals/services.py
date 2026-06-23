"""Approvals + Ledger engine services.

State machine: PENDING -> APPROVED | REJECTED | CANCELLED; APPROVED -> DISBURSED
(money-moving kinds) writes an immutable LedgerEntry. Every transition is locked
with select_for_update so concurrent approve/disburse can't double-act.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.approvals.models import ApprovalRequest, LedgerEntry
from core.exceptions import NotFoundException, UnprocessableEntity


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
    return ApprovalRequest.objects.create(
        kind=kind,
        title=title,
        requested_by=requested_by,
        amount_uzs=amount_uzs,
        description=description,
        branch=branch,
        payload=payload or {},
    )


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
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    return req


@transaction.atomic
def reject(*, request_id: int, actor=None, note: str = "") -> ApprovalRequest:
    req = _locked(request_id)
    if req.status not in (ApprovalRequest.Status.PENDING, ApprovalRequest.Status.APPROVED):
        raise UnprocessableEntity(_("This request can no longer be rejected."), code="approval_not_rejectable")
    req.status = ApprovalRequest.Status.REJECTED
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.decision_note = note
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    return req


@transaction.atomic
def cancel(*, request_id: int, actor=None) -> ApprovalRequest:
    """Requester withdraws a still-pending request (ownership enforced by the view)."""
    req = _locked(request_id)
    if req.status != ApprovalRequest.Status.PENDING:
        raise UnprocessableEntity(_("Only a pending request can be cancelled."), code="approval_not_cancellable")
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
        raise UnprocessableEntity(_("Only an approved request can be disbursed."), code="approval_not_approved")
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
        update_fields=["status", "disbursed_by", "disbursed_at", "payment_method", "ledger_entry", "updated_at"]
    )
    return req
