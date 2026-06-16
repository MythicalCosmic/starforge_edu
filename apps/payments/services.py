"""Payments write-side services (D3-B-6..11).

All writes here: idempotency-keyed Payment creation, the Payme JSON-RPC store,
webhook intake with replay protection, checkout + auto-allocation (Lane A's
``allocate_payment`` via LAZY import — it lands in a different lane), the refund
flow (drives ``finance.Refund`` via lazy import), and the single chokepoint that
flips a Payment to completed/failed and emits the matching signal exactly once.

Cross-app SERVICE calls are imported LAZILY inside the function (Lane A merges
before B but is built in parallel) — never at module top.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.payments.models import (
    FiscalReceipt,
    Payment,
    PaymentAttempt,
    Provider,
    ProviderConfig,
    WebhookEvent,
)
from apps.payments.signals import payment_completed, payment_failed
from core.exceptions import UnprocessableEntity, ValidationException
from core.utils import current_schema, stable_hash
from infrastructure.payments.payme import (
    ERR_ACCOUNT_NOT_FOUND,
    STATE_CANCELLED,
    STATE_CANCELLED_AFTER_PERFORM,
    STATE_CREATED,
    STATE_PERFORMED,
    PaymeError,
)

_TIYIN = Decimal("100")


# ---------------------------------------------------------------------------
# Idempotent payment creation (D3-B-6)
# ---------------------------------------------------------------------------
@transaction.atomic
def get_or_create_payment(
    *,
    idempotency_key: str,
    provider: str,
    amount_uzs: Decimal,
    account_ref: str = "",
    payer=None,
    metadata: dict[str, Any] | None = None,
) -> tuple[Payment, bool]:
    """Return ``(payment, created)``. The same idempotency key always returns the
    existing row — never a duplicate (the unique constraint is the backstop).
    """
    if not idempotency_key:
        raise ValidationException(_("idempotency_key is required."), fields={"idempotency_key": ["required"]})
    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing, False
    payment = Payment.objects.create(
        idempotency_key=idempotency_key,
        provider=provider,
        amount_uzs=amount_uzs,
        account_ref=account_ref,
        payer=payer,
        metadata=metadata or {},
    )
    return payment, True


def _record_attempt(
    payment: Payment, *, request_payload: dict, response_payload: dict, error_code: str = ""
) -> None:
    attempt_no = payment.attempts.count() + 1
    PaymentAttempt.objects.create(
        payment=payment,
        attempt_no=attempt_no,
        request_payload=request_payload,
        response_payload=response_payload,
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# State transition chokepoint + signals (D3-B-11)
# ---------------------------------------------------------------------------
def _invoice_and_student_for(payment: Payment) -> tuple[int | None, int | None]:
    """Best-effort resolution of (invoice_id, student_id) for signal kwargs.
    Lazy finance import — finance lands in another lane."""
    invoice_id = payment.metadata.get("invoice_id")
    student_id = payment.metadata.get("student_id")
    if invoice_id and not student_id:
        try:
            from apps.finance.models import Invoice

            inv = Invoice.objects.filter(pk=invoice_id).values_list("student_id", flat=True).first()
            student_id = inv
        except Exception:  # finance not migrated yet / row gone — signal still fires
            student_id = None
    return invoice_id, student_id


@transaction.atomic
def mark_payment_completed(
    *, payment_id: int, provider_txn_id: str = "", auto_allocate: bool = True
) -> Payment:
    """Flip a Payment to completed ONCE. Idempotent: a re-call on an already
    completed payment is a no-op (no second signal, no second allocation)."""
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.status == Payment.Status.COMPLETED:
        return payment
    payment.status = Payment.Status.COMPLETED
    payment.paid_at = timezone.now()
    if provider_txn_id:
        payment.provider_txn_id = provider_txn_id
    payment.save(update_fields=["status", "paid_at", "provider_txn_id", "updated_at"])

    if auto_allocate:
        _auto_allocate(payment)

    schema = current_schema()
    invoice_id, student_id = _invoice_and_student_for(payment)
    amount = str(payment.amount_uzs)
    transaction.on_commit(
        lambda: payment_completed.send(
            sender=Payment,
            payment_id=payment.pk,
            invoice_id=invoice_id,
            student_id=student_id,
            amount_uzs=amount,
            schema_name=schema,
        )
    )
    # Post-payment fiscalization (D3-B-9) — Celery, idempotent.
    transaction.on_commit(lambda: _enqueue_fiscalization(payment.pk, schema))
    return payment


@transaction.atomic
def mark_payment_failed(*, payment_id: int, cancel_reason: int | None = None) -> Payment:
    """Flip a Payment to failed ONCE (no second signal on re-call)."""
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.status in (Payment.Status.FAILED, Payment.Status.CANCELLED):
        return payment
    payment.status = Payment.Status.FAILED
    if cancel_reason is not None:
        payment.cancel_reason = cancel_reason
    payment.save(update_fields=["status", "cancel_reason", "updated_at"])

    schema = current_schema()
    invoice_id, student_id = _invoice_and_student_for(payment)
    amount = str(payment.amount_uzs)
    transaction.on_commit(
        lambda: payment_failed.send(
            sender=Payment,
            payment_id=payment.pk,
            invoice_id=invoice_id,
            student_id=student_id,
            amount_uzs=amount,
            schema_name=schema,
        )
    )
    return payment


def _enqueue_fiscalization(payment_id: int, schema: str) -> None:
    from celery_tasks.payment_tasks import fiscalize_payment

    fiscalize_payment.delay(payment_id, _schema_name=schema)


# ---------------------------------------------------------------------------
# Auto-allocation (D3-B-7) — Lane A's allocate_payment via lazy import
# ---------------------------------------------------------------------------
def _auto_allocate(payment: Payment) -> None:
    """If the payment amount matches a single invoice exactly, auto-allocate via
    Lane A's service; otherwise flag for manual review."""
    invoice_id = payment.metadata.get("invoice_id")
    if not invoice_id:
        payment.allocation_status = Payment.Allocation.MANUAL_REVIEW
        payment.save(update_fields=["allocation_status", "updated_at"])
        return
    try:
        from apps.finance.services import allocate_payment
    except Exception:
        # Lane A not present in this schema yet — leave allocation for the
        # manual endpoint; the payment itself is completed and signalled.
        payment.allocation_status = Payment.Allocation.MANUAL_REVIEW
        payment.save(update_fields=["allocation_status", "updated_at"])
        return
    allocate_payment(payment_id=payment.pk, amount_uzs=payment.amount_uzs, invoice_ids=[int(invoice_id)])
    payment.allocation_status = Payment.Allocation.ALLOCATED
    payment.save(update_fields=["allocation_status", "updated_at"])


@transaction.atomic
def allocate_manual(*, payment_id: int, allocations: list[dict[str, Any]]) -> Payment:
    """Manual allocation endpoint body — drives Lane A per (invoice, amount)."""
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.status != Payment.Status.COMPLETED:
        raise UnprocessableEntity(_("Only completed payments can be allocated."))
    from apps.finance.services import allocate_payment

    for alloc in allocations:
        allocate_payment(
            payment_id=payment.pk,
            amount_uzs=Decimal(str(alloc["amount"])),
            invoice_ids=[int(alloc["invoice"])],
        )
    payment.allocation_status = Payment.Allocation.ALLOCATED
    payment.save(update_fields=["allocation_status", "updated_at"])
    return payment


# ---------------------------------------------------------------------------
# Checkout (D3-B-7)
# ---------------------------------------------------------------------------
@transaction.atomic
def create_checkout(*, invoice_id: int, provider: str, idempotency_key: str, payer=None) -> dict[str, Any]:
    """Create (or fetch) a pending Payment for an invoice and return the client's
    redirect/payload. Idempotent on ``idempotency_key`` (TASKS §16)."""
    if provider not in Provider.values:
        raise ValidationException(_("Unknown provider."), fields={"provider": ["invalid"]})
    from apps.finance.models import Invoice

    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None:
        raise UnprocessableEntity(_("Invoice not found."), fields={"invoice": ["not_found"]})

    payment, _created = get_or_create_payment(
        idempotency_key=idempotency_key,
        provider=provider,
        amount_uzs=invoice.total_uzs,
        account_ref=invoice.number,
        payer=payer,
        metadata={"invoice_id": invoice_id, "student_id": invoice.student_id},
    )

    config = ProviderConfig.objects.filter(provider=provider, is_active=True).first()
    account = {"invoice": invoice.number}
    payload = _build_provider_checkout(provider=provider, payment=payment, config=config, account=account)
    return {"payment_id": payment.pk, "provider": provider, **payload}


def _build_provider_checkout(*, provider: str, payment: Payment, config, account: dict) -> dict[str, Any]:
    amount_uzs = int(payment.amount_uzs)
    if provider == Provider.CLICK:
        from infrastructure.payments.click import get_click_client

        return get_click_client().build_checkout(
            amount_uzs=amount_uzs, merchant_trans_id=str(payment.pk), config=config
        )
    if provider == Provider.PAYME:
        from infrastructure.payments.payme import get_payme_client

        return get_payme_client().build_checkout(
            amount_tiyin=int(payment.amount_uzs * _TIYIN), account=account, config=config
        )
    if provider == Provider.UZUM:
        from infrastructure.payments.uzum import get_uzum_client

        return get_uzum_client().build_checkout(
            amount_uzs=amount_uzs, order_id=str(payment.pk), config=config
        )
    return {}


# ---------------------------------------------------------------------------
# Webhook intake + replay protection (D3-B-5, D3-B-6)
# ---------------------------------------------------------------------------
@transaction.atomic
def record_webhook_event(
    *, provider: str, event_id: str, payload: dict, remote_ip: str | None, signature_valid: bool
) -> tuple[WebhookEvent, bool]:
    """Insert a WebhookEvent. Returns ``(event, is_new)``. A replayed
    ``(provider, event_id)`` returns the existing row marked ``duplicate`` and
    ``is_new=False`` — the caller must NOT re-run side effects (D3-B-6)."""
    existing = WebhookEvent.objects.filter(provider=provider, event_id=event_id).first()
    if existing is not None:
        # P0 fix (D3-F): a replay must be recorded as `duplicate`, not silently
        # returned with its prior status — this is the audit signal that a nonce
        # was reused, and D3-B-6 / the replay tests assert it.
        if existing.status != WebhookEvent.Status.DUPLICATE:
            existing.status = WebhookEvent.Status.DUPLICATE
            existing.save(update_fields=["status"])
        return existing, False
    status = WebhookEvent.Status.RECEIVED if signature_valid else WebhookEvent.Status.REJECTED
    event = WebhookEvent.objects.create(
        provider=provider,
        event_id=event_id,
        payload=payload,
        remote_ip=remote_ip or None,
        signature_valid=signature_valid,
        status=status,
    )
    return event, True


def mark_webhook_processed(event: WebhookEvent) -> None:
    event.status = WebhookEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])


# ---------------------------------------------------------------------------
# Payme JSON-RPC store (D3-B-3) — the DB side the PaymeClient delegates to
# ---------------------------------------------------------------------------
# The account-field name the merchant configures in the Payme cabinet (e.g.
# ``order_id``, ``invoice``). The webhook builders use ``order_id``; we accept
# any of these and echo the offending field name back in a Payme ``data`` member.
_PAYME_ACCOUNT_FIELDS = ("order_id", "invoice", "invoice_number", "account")


def _account_field(account: dict[str, Any]) -> tuple[str, str]:
    """Return ``(field_name, value)`` for the account's invoice-number field.

    Tries the known field names in order so a tenant configured with ``order_id``
    or ``invoice`` both resolve; the chosen field name is what a Payme account
    error names in its ``data`` member (DAY-3.md D3-B-3)."""
    for field in _PAYME_ACCOUNT_FIELDS:
        value = account.get(field)
        if value:
            return field, str(value)
    # Nothing usable — name the canonical configured field in `data`.
    return _PAYME_ACCOUNT_FIELDS[0], ""


class PaymeDBStore:
    """Implements ``infrastructure.payments.payme.PaymeStore`` against this
    tenant's Payment/Invoice rows. Account errors raise ``PaymeError`` with the
    code in -31050..-31099 and a ``data`` field naming the offender."""

    def find_account(self, account: dict[str, Any]):
        field, invoice_number = _account_field(account)
        if not invoice_number:
            raise PaymeError(ERR_ACCOUNT_NOT_FOUND, _ml("Invoice number is required."), data=field)
        from apps.finance.models import Invoice

        invoice = Invoice.objects.filter(number=invoice_number).first()
        if invoice is None:
            raise PaymeError(ERR_ACCOUNT_NOT_FOUND, _ml("Invoice not found."), data=field)
        return invoice

    def expected_amount_tiyin(self, invoice) -> int:
        return int(invoice.total_uzs * _TIYIN)

    def get_transaction(self, payme_id: str):
        return Payment.objects.filter(provider=Provider.PAYME, provider_txn_id=payme_id).first()

    @transaction.atomic
    def create_transaction(self, *, payme_id: str, time_ms: int, amount_tiyin: int, account: dict, invoice):
        field, account_value = _account_field(account)
        # One open transaction per account: another open/performed Payme txn for
        # the same invoice → -31099 (account already paid/locked).
        conflicting = (
            Payment.objects.filter(provider=Provider.PAYME, account_ref=account_value)
            .exclude(provider_txn_id=payme_id)
            .filter(provider_state__in=[STATE_CREATED, STATE_PERFORMED])
            .exists()
        )
        if conflicting:
            from infrastructure.payments.payme import ERR_ACCOUNT_ALREADY_PAID

            raise PaymeError(ERR_ACCOUNT_ALREADY_PAID, _ml("Another transaction is in progress."), data=field)
        key = f"payme:{current_schema()}:{payme_id}"
        payment, _created = get_or_create_payment(
            idempotency_key=key,
            provider=Provider.PAYME,
            amount_uzs=Decimal(amount_tiyin) / _TIYIN,
            account_ref=account_value,
            metadata={"invoice_id": invoice.pk, "student_id": invoice.student_id, "account": account},
        )
        payment.provider_txn_id = payme_id
        payment.provider_state = STATE_CREATED
        payment.provider_created_at_ms = time_ms
        payment.status = Payment.Status.PROCESSING
        payment.save(
            update_fields=[
                "provider_txn_id",
                "provider_state",
                "provider_created_at_ms",
                "status",
                "updated_at",
            ]
        )
        return payment

    def perform_transaction(self, txn: Payment):
        now_ms = int(timezone.now().timestamp() * 1000)
        txn.provider_state = STATE_PERFORMED
        txn.metadata = {**txn.metadata, "perform_time_ms": now_ms}
        txn.save(update_fields=["provider_state", "metadata", "updated_at"])
        mark_payment_completed(payment_id=txn.pk, provider_txn_id=txn.provider_txn_id)
        txn.refresh_from_db()
        return txn

    def cancel_transaction(self, txn: Payment, *, reason: int):
        now_ms = int(timezone.now().timestamp() * 1000)
        was_performed = txn.provider_state == STATE_PERFORMED
        txn.provider_state = STATE_CANCELLED_AFTER_PERFORM if was_performed else STATE_CANCELLED
        txn.cancel_reason = reason
        txn.metadata = {**txn.metadata, "cancel_time_ms": now_ms}
        txn.save(update_fields=["provider_state", "cancel_reason", "metadata", "updated_at"])
        if was_performed:
            # State -2: cancel after perform → drive a finance Refund (D3-B-8).
            _refund_for_cancelled_payment(txn, reason=reason)
            txn.status = Payment.Status.REFUNDED
            txn.save(update_fields=["status", "updated_at"])
        else:
            mark_payment_failed(payment_id=txn.pk, cancel_reason=reason)
            txn.refresh_from_db()
        return txn

    def statement(self, *, frm: int, to: int) -> list[dict[str, Any]]:
        qs = Payment.objects.filter(
            provider=Provider.PAYME, provider_created_at_ms__gte=frm, provider_created_at_ms__lte=to
        ).order_by("provider_created_at_ms")
        return [
            {
                "id": p.provider_txn_id,
                "time": p.provider_created_at_ms,
                "amount": int(p.amount_uzs * _TIYIN),
                "account": p.metadata.get("account", {}),
                "create_time": p.create_time_ms,
                "perform_time": p.perform_time_ms,
                "cancel_time": p.cancel_time_ms,
                "transaction": p.provider_txn_id,
                "state": p.provider_state,
                "reason": p.cancel_reason,
            }
            for p in qs
        ]


def _ml(text: str) -> dict[str, str]:
    """Payme localized message triplet."""
    return {"ru": text, "uz": text, "en": text}


# ---------------------------------------------------------------------------
# Refund flow (D3-B-8) — drives finance.Refund via lazy import
# ---------------------------------------------------------------------------
def _refund_for_cancelled_payment(payment: Payment, *, reason: int) -> None:
    invoice_id = payment.metadata.get("invoice_id")
    if not invoice_id:
        return
    try:
        from apps.finance.models import Invoice
        from apps.finance.services import register_refund_completion, request_refund
    except Exception:
        return  # finance not present yet — refund recorded only on the payment row
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None:
        return
    refund = request_refund(
        invoice=invoice,
        payment_id=payment.pk,
        amount_uzs=payment.amount_uzs,
        reason=f"payme_cancel:{reason}",
    )
    register_refund_completion(refund_id=refund.pk, payment_id=payment.pk)


@transaction.atomic
def refund_payment(*, payment_id: int, amount_uzs: Decimal | None = None, reason: str = "") -> Payment:
    """Refund a completed payment — drives Lane A's Refund state machine."""
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.status != Payment.Status.COMPLETED:
        raise UnprocessableEntity(_("Only completed payments can be refunded."))
    invoice_id = payment.metadata.get("invoice_id")
    if not invoice_id:
        raise UnprocessableEntity(_("Payment is not linked to an invoice."))
    from apps.finance.models import Invoice
    from apps.finance.services import register_refund_completion, request_refund

    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None:
        raise UnprocessableEntity(_("Linked invoice not found."))
    refund = request_refund(
        invoice=invoice,
        payment_id=payment.pk,
        amount_uzs=amount_uzs or payment.amount_uzs,
        reason=reason or "manual_refund",
    )
    register_refund_completion(refund_id=refund.pk, payment_id=payment.pk)
    payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=["status", "updated_at"])
    return payment


# ---------------------------------------------------------------------------
# Click / Uzum webhook processing (D3-B-2, D3-B-4)
# ---------------------------------------------------------------------------
@transaction.atomic
def process_click_complete(*, payload: dict, invoice) -> Payment:
    """Click action=1 (complete) → completed Payment for the invoice."""
    click_trans_id = str(payload.get("click_trans_id", ""))
    key = f"click:{current_schema()}:{click_trans_id}"
    payment, _created = get_or_create_payment(
        idempotency_key=key,
        provider=Provider.CLICK,
        amount_uzs=invoice.total_uzs,
        account_ref=invoice.number,
        metadata={"invoice_id": invoice.pk, "student_id": invoice.student_id},
    )
    payment.provider_txn_id = click_trans_id
    payment.save(update_fields=["provider_txn_id", "updated_at"])
    mark_payment_completed(payment_id=payment.pk, provider_txn_id=click_trans_id)
    payment.refresh_from_db()
    return payment


@transaction.atomic
def process_uzum_payment(*, payload: dict, invoice) -> Payment:
    txn_id = str(payload.get("transaction_id") or payload.get("event_id") or payload.get("order_id", ""))
    key = f"uzum:{current_schema()}:{txn_id}"
    payment, _created = get_or_create_payment(
        idempotency_key=key,
        provider=Provider.UZUM,
        amount_uzs=invoice.total_uzs,
        account_ref=invoice.number,
        metadata={"invoice_id": invoice.pk, "student_id": invoice.student_id},
    )
    payment.provider_txn_id = txn_id
    payment.save(update_fields=["provider_txn_id", "updated_at"])
    mark_payment_completed(payment_id=payment.pk, provider_txn_id=txn_id)
    payment.refresh_from_db()
    return payment


# ---------------------------------------------------------------------------
# Fiscalization task body (D3-B-9) — idempotent
# ---------------------------------------------------------------------------
@transaction.atomic
def fiscalize_payment_body(payment_id: int) -> str | None:
    """Idempotent: an existing CONFIRMED FiscalReceipt short-circuits. Returns
    the fiscal sign. Stores the marker on the receipt row so a retry no-ops."""
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    receipt, _created = FiscalReceipt.objects.get_or_create(payment=payment)
    if receipt.status == FiscalReceipt.Status.CONFIRMED:
        return receipt.fiscal_sign
    if payment.status != Payment.Status.COMPLETED:
        raise UnprocessableEntity(_("Only completed payments are fiscalized."))

    from infrastructure.fiscal import get_fiscal_client

    key = stable_hash(f"fiscal:{current_schema()}:{payment.pk}")
    receipt.status = FiscalReceipt.Status.SUBMITTED
    receipt.attempts = receipt.attempts + 1
    receipt.submitted_at = timezone.now()
    receipt.save(update_fields=["status", "attempts", "submitted_at", "updated_at"])

    result = get_fiscal_client().fiscalize(
        payment_id=payment.pk,
        amount_uzs=str(payment.amount_uzs),
        items=[{"name": payment.account_ref or "payment", "amount": str(payment.amount_uzs), "qty": 1}],
        idempotency_key=key,
    )
    receipt.fiscal_sign = result["fiscal_sign"]
    receipt.qr_url = result["qr_url"]
    receipt.payload = result.get("raw", {})
    receipt.status = FiscalReceipt.Status.CONFIRMED
    receipt.confirmed_at = timezone.now()
    receipt.save(update_fields=["fiscal_sign", "qr_url", "payload", "status", "confirmed_at", "updated_at"])
    return receipt.fiscal_sign


def enqueue_receipt_pdf(payment_id: int, schema: str) -> None:
    """Enqueue the off-request receipt-PDF render (TD-14). Called on-demand from
    the receipt endpoint, NOT from fiscalization — so the payment-completion
    chokepoint never couples to weasyprint (absent on the dev box)."""
    from celery_tasks.payment_tasks import generate_receipt_pdf

    generate_receipt_pdf.delay(payment_id, _schema_name=schema)


def mark_fiscal_failed(payment_id: int, exc: Exception) -> None:
    FiscalReceipt.objects.filter(payment_id=payment_id).exclude(status=FiscalReceipt.Status.CONFIRMED).update(
        status=FiscalReceipt.Status.FAILED, payload={"error": str(exc)[:2000]}
    )


# ---------------------------------------------------------------------------
# Receipt PDF (D3-B-10) — weasyprint LAZY, S3 → signed URL (TD-14)
# ---------------------------------------------------------------------------
def _render_receipt_pdf(payment: Payment, receipt: FiscalReceipt) -> bytes:
    """weasyprint is imported lazily so the app loads where its GTK native libs
    are absent (Windows dev box); only this call needs them (mirrors the academics
    transcript renderer)."""
    from django.template.loader import render_to_string
    from django.utils import translation
    from weasyprint import HTML  # lazy on purpose: GTK native libs only needed here

    lang = getattr(getattr(payment.payer, "preferred_language", None), "lower", lambda: "en")()
    if lang not in ("uz", "ru", "en"):
        lang = "en"
    with translation.override(lang):
        html = render_to_string(
            f"documents/receipt_{lang}.html",
            {"payment": payment, "receipt": receipt},
        )
    return HTML(string=html).write_pdf()


@transaction.atomic
def generate_receipt_pdf_body(payment_id: int) -> str | None:
    """Idempotent: returns the existing key if already rendered. Stores the S3 key
    on ``FiscalReceipt.payload['pdf_key']`` so the receipt endpoint can sign it."""
    payment = Payment.objects.select_for_update().select_related("payer").get(pk=payment_id)
    receipt = getattr(payment, "fiscal_receipt", None)
    if receipt is None:
        raise UnprocessableEntity(_("Payment has no fiscal receipt yet."))
    existing = (receipt.payload or {}).get("pdf_key")
    if existing:
        return existing

    from infrastructure.storage.s3_client import upload_bytes

    pdf = _render_receipt_pdf(payment, receipt)
    key = f"{current_schema()}/receipts/{payment.pk}.pdf"
    upload_bytes(key, pdf, content_type="application/pdf")
    receipt.payload = {**(receipt.payload or {}), "pdf_key": key}
    receipt.save(update_fields=["payload", "updated_at"])
    return key


# Re-export for the webhook handler's convenience.
__all__ = [
    "PaymeDBStore",
    "allocate_manual",
    "create_checkout",
    "enqueue_receipt_pdf",
    "fiscalize_payment_body",
    "generate_receipt_pdf_body",
    "get_or_create_payment",
    "mark_fiscal_failed",
    "mark_payment_completed",
    "mark_payment_failed",
    "process_click_complete",
    "process_uzum_payment",
    "record_webhook_event",
    "refund_payment",
]
