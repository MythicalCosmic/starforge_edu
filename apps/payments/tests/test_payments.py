"""Lane B service-level tests (D3-B-6..11) — the non-attack half of the matrix.

These exercise the payments services directly inside ``schema_context`` (the
webhook/attack surface lives in test_webhook_attacks / test_payme_spec):

- fiscalization task idempotency (D3-B-9) — a second run reuses the confirmed
  ``FiscalReceipt`` and the mock fiscal sign is deterministic;
- reconciliation math (D3-B-10) — paid vs allocated totals + the mismatch list;
- Click prepare/complete happy path (D3-B-2) drives a completed Payment +
  single allocation;
- refund flow (D3-B-8) rejects a refund on a non-completed Payment;
- ``payment_completed`` / ``payment_failed`` fire exactly once per transition
  (D3-B-11).

Lane code is imported lazily/locally; the orchestrator runs this on Postgres
after A..E merge (finance.Refund / allocate_payment land in Lane A).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django_tenants.utils import schema_context

from apps.payments.tests import _helpers as helpers

pytestmark = pytest.mark.django_db

AMOUNT_UZS = "150000.00"


@pytest.fixture
def invoice_a(tenant_a):
    helpers.seed_provider_configs(tenant_a)
    inv = helpers.seed_open_invoice(tenant_a, number="INV-2026-000001", amount_uzs=AMOUNT_UZS)
    return tenant_a, inv


# --------------------------------------------------------------------------- #
# Fiscalization idempotency (D3-B-9) — mock determinism + short-circuit
# --------------------------------------------------------------------------- #
def test_fiscalize_payment_idempotent_and_deterministic(invoice_a):
    tenant_a, inv = invoice_a
    from apps.payments import services
    from apps.payments.models import FiscalReceipt, Payment

    with schema_context(tenant_a.schema_name):
        payment, _ = services.get_or_create_payment(
            idempotency_key="fisc-1",
            provider="payme",
            amount_uzs=Decimal(AMOUNT_UZS),
            account_ref=inv.number,
            metadata={"invoice_id": inv.id, "student_id": inv.student_id},
        )
        # Drive it completed WITHOUT auto-allocation noise; fiscalize directly.
        Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.COMPLETED)

        first = services.fiscalize_payment_body(payment.pk)
        second = services.fiscalize_payment_body(payment.pk)

        assert first == second, "same payment must fiscalize to the same sign (mock determinism)"
        receipts = FiscalReceipt.objects.filter(payment=payment)
        assert receipts.count() == 1
        receipt = receipts.get()
        assert receipt.status == FiscalReceipt.Status.CONFIRMED
        assert receipt.fiscal_sign == first
        assert receipt.qr_url
        # attempts incremented exactly once — the confirmed receipt short-circuits.
        assert receipt.attempts == 1


def test_fiscalize_rejects_non_completed_payment(invoice_a):
    tenant_a, inv = invoice_a
    from apps.payments import services
    from core.exceptions import UnprocessableEntity

    with schema_context(tenant_a.schema_name):
        payment, _ = services.get_or_create_payment(
            idempotency_key="fisc-pending",
            provider="payme",
            amount_uzs=Decimal(AMOUNT_UZS),
            account_ref=inv.number,
        )
        with pytest.raises(UnprocessableEntity):
            services.fiscalize_payment_body(payment.pk)


# --------------------------------------------------------------------------- #
# Click prepare/complete happy path (D3-B-2) + signal once (D3-B-11)
# --------------------------------------------------------------------------- #
def test_click_complete_completes_payment_and_allocates(invoice_a, django_capture_on_commit_callbacks):
    tenant_a, inv = invoice_a
    from apps.payments import services
    from apps.payments.models import Payment
    from apps.payments.signals import payment_completed

    completed_signals: list[dict] = []
    # weak=False: a bare-lambda receiver has no strong ref and would be GC'd
    # before dispatch (Django drops dead weakrefs), making the listener silently
    # never fire. The production receiver (notifications) also connects weak=False.
    payment_completed.connect(
        lambda sender, **kwargs: completed_signals.append(kwargs),
        dispatch_uid="test.click.completed",
        weak=False,
    )
    try:
        with schema_context(tenant_a.schema_name):
            # execute=True runs the transaction.on_commit callbacks (signals) so
            # the emit-on-commit contract is exercised (mirrors attendance tests).
            with django_capture_on_commit_callbacks(execute=True):
                payment = services.process_click_complete(
                    payload={"click_trans_id": "click-1", "merchant_trans_id": inv.number},
                    invoice=inv,
                )
            payment.refresh_from_db()
            assert payment.status == Payment.Status.COMPLETED
            assert payment.provider_txn_id == "click-1"
            assert payment.paid_at is not None
            allocs = helpers.allocation_rows(tenant_a, payment_id=payment.pk)
            assert len(allocs) == 1
            assert allocs[0].amount_uzs == Decimal(AMOUNT_UZS)
            assert payment.allocation_status == Payment.Allocation.ALLOCATED
    finally:
        payment_completed.disconnect(dispatch_uid="test.click.completed")

    # exactly one payment_completed for the single transition
    assert len(completed_signals) == 1
    assert completed_signals[0]["payment_id"] == payment.pk
    assert completed_signals[0]["invoice_id"] == inv.id
    assert completed_signals[0]["amount_uzs"] == AMOUNT_UZS


def test_mark_payment_completed_twice_emits_one_signal(invoice_a, django_capture_on_commit_callbacks):
    tenant_a, inv = invoice_a
    from apps.payments import services
    from apps.payments.signals import payment_completed

    fired: list[dict] = []
    # weak=False: see test_click_complete_completes_payment_and_allocates — a bare
    # lambda would be garbage-collected before the signal dispatches.
    payment_completed.connect(
        lambda sender, **kw: fired.append(kw), dispatch_uid="test.once.completed", weak=False
    )
    try:
        with schema_context(tenant_a.schema_name):
            payment, _ = services.get_or_create_payment(
                idempotency_key="once-1",
                provider="click",
                amount_uzs=Decimal(AMOUNT_UZS),
                account_ref=inv.number,
                metadata={"invoice_id": inv.id, "student_id": inv.student_id},
            )
            with django_capture_on_commit_callbacks(execute=True):
                services.mark_payment_completed(payment_id=payment.pk, provider_txn_id="t1")
            with django_capture_on_commit_callbacks(execute=True):
                # second transition is a no-op — no second signal registered
                services.mark_payment_completed(payment_id=payment.pk, provider_txn_id="t1")
    finally:
        payment_completed.disconnect(dispatch_uid="test.once.completed")
    assert len(fired) == 1, "completion signal must fire exactly once per transition"


# --------------------------------------------------------------------------- #
# Refund flow (D3-B-8)
# --------------------------------------------------------------------------- #
def test_refund_on_non_completed_payment_rejected(invoice_a):
    tenant_a, inv = invoice_a
    from apps.payments import services
    from core.exceptions import UnprocessableEntity

    with schema_context(tenant_a.schema_name):
        payment, _ = services.get_or_create_payment(
            idempotency_key="refund-pending",
            provider="payme",
            amount_uzs=Decimal(AMOUNT_UZS),
            account_ref=inv.number,
            metadata={"invoice_id": inv.id, "student_id": inv.student_id},
        )
        with pytest.raises(UnprocessableEntity):
            services.refund_payment(payment_id=payment.pk, reason="oops")


def test_refund_completed_payment_drives_finance_refund(invoice_a):
    tenant_a, inv = invoice_a
    from apps.payments import services
    from apps.payments.models import Payment

    with schema_context(tenant_a.schema_name):
        # complete + allocate first, so the invoice has a paid amount to reverse
        payment = services.process_click_complete(
            payload={"click_trans_id": "click-refund", "merchant_trans_id": inv.number},
            invoice=inv,
        )
        services.refund_payment(payment_id=payment.pk, reason="customer_request")
        payment.refresh_from_db()
        assert payment.status == Payment.Status.REFUNDED

        from apps.finance.models import Refund

        refund = Refund.objects.filter(payment_id=payment.pk).first()
        assert refund is not None
        assert refund.state == Refund.State.COMPLETED


# --------------------------------------------------------------------------- #
# Reconciliation math (D3-B-10)
# --------------------------------------------------------------------------- #
def test_reconciliation_totals_and_mismatch(invoice_a):
    tenant_a, inv = invoice_a
    from django.utils import timezone

    from apps.payments import selectors, services
    from apps.payments.models import Payment

    with schema_context(tenant_a.schema_name):
        # one fully-allocated payment (matches), one completed-but-unallocated (mismatch)
        matched = services.process_click_complete(
            payload={"click_trans_id": "rec-matched", "merchant_trans_id": inv.number},
            invoice=inv,
        )
        unallocated, _ = services.get_or_create_payment(
            idempotency_key="rec-unalloc",
            provider="cash",
            amount_uzs=Decimal("50000.00"),
            account_ref="INV-NONE",
        )
        Payment.objects.filter(pk=unallocated.pk).update(
            status=Payment.Status.COMPLETED, paid_at=timezone.now()
        )

        report = selectors.reconciliation(on=timezone.localdate())

        assert report["total_paid_uzs"] == "200000.00"  # 150000 + 50000
        assert report["total_allocated_uzs"] == "150000.00"  # only the matched one
        # the unallocated completed payment is a mismatch
        mismatch_ids = {m["payment_id"] for m in report["mismatches"]}
        assert unallocated.pk in mismatch_ids
        assert matched.pk not in mismatch_ids
        assert report["mismatch_count"] == 1
        assert report["by_provider"]["click"] == "150000.00"
        assert report["by_provider"]["cash"] == "50000.00"


# --------------------------------------------------------------------------- #
# ProviderConfig credentials write-only (D3-B-1 / TD-11)
# --------------------------------------------------------------------------- #
def test_provider_config_serializer_hides_credentials(invoice_a):
    tenant_a, _ = invoice_a
    from apps.payments.models import ProviderConfig
    from apps.payments.serializers import ProviderConfigSerializer

    with schema_context(tenant_a.schema_name):
        config = ProviderConfig.objects.get(provider="payme")
        data = ProviderConfigSerializer(config).data
        assert "payme_key" not in data
        assert "payme_test_key" not in data
        assert "uzum_api_key" not in data
        assert "click_secret_key" not in data
        # non-secret fields still present
        assert data["provider"] == "payme"
