from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.test import override_settings
from django_tenants.utils import schema_context

from apps.payments.models import Payment
from infrastructure.payments.payme import (
    ERR_ACCOUNT_ALREADY_PAID,
    STATE_CANCELLED,
    STATE_CANCELLED_AFTER_PERFORM,
    STATE_CREATED,
    STATE_PERFORMED,
    PaymeError,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_payme_create_allows_one_open_transaction_per_invoice(tenant_a):
    from apps.payments import services
    from apps.payments.tests import _helpers as helpers

    invoice = helpers.seed_open_invoice(
        tenant_a,
        number="INV-PAYME-CREATE-RACE-1",
        amount_uzs="150000.00",
    )
    barrier = Barrier(2)

    def run(payme_id: str):
        close_old_connections()
        try:
            with schema_context(tenant_a.schema_name):
                from apps.finance.models import Invoice

                stale_invoice = Invoice.objects.get(pk=invoice.pk)
                barrier.wait(timeout=10)
                try:
                    payment = services.PaymeDBStore().create_transaction(
                        payme_id=payme_id,
                        time_ms=1_700_000_000_000,
                        amount_tiyin=15_000_000,
                        account={"invoice": invoice.number},
                        invoice=stale_invoice,
                    )
                    return ("ok", payment.pk)
                except PaymeError as exc:
                    return ("payme_error", exc.code)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("payme-create-race-a", "payme-create-race-b")))

    assert sorted(kind for kind, _value in results) == ["ok", "payme_error"]
    assert [value for kind, value in results if kind == "payme_error"] == [ERR_ACCOUNT_ALREADY_PAID]
    with schema_context(tenant_a.schema_name):
        assert (
            Payment.objects.filter(
                provider=Payment.Method.PAYME,
                account_ref=invoice.number,
                provider_state=STATE_CREATED,
            ).count()
            == 1
        )


def test_concurrent_payme_perform_cancel_never_resurrects_payment(tenant_a, monkeypatch):
    """Two requests begin with the same stale CREATED object.

    Each service transition must re-fetch and lock the row. Depending on lock
    order, cancel either wins before perform or confirms a refund after perform;
    neither ordering may leave a completed payment with a cancelled Payme state.
    """
    from apps.finance.models import PaymentAllocation, Refund
    from apps.payments import services
    from apps.payments.tests import _helpers as helpers

    monkeypatch.setattr(services, "_enqueue_fiscalization", lambda *_args, **_kwargs: None)
    invoice = helpers.seed_open_invoice(tenant_a, number="INV-PAYME-RACE-1", amount_uzs="150000.00")
    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.create(
            provider=Payment.Method.PAYME,
            amount_uzs=Decimal("150000.00"),
            status=Payment.Status.PROCESSING,
            idempotency_key="payme-race-1",
            provider_txn_id="payme-race-1",
            provider_state=STATE_CREATED,
            provider_created_at_ms=1_700_000_000_000,
            account_ref=invoice.number,
            metadata={"invoice_id": invoice.pk, "student_id": invoice.student_id},
        )
        payment_id = payment.pk

    barrier = Barrier(2)

    def run(action: str):
        close_old_connections()
        try:
            with schema_context(tenant_a.schema_name):
                stale = Payment.objects.get(pk=payment_id)
                barrier.wait(timeout=10)
                store = services.PaymeDBStore()
                try:
                    if action == "perform":
                        result = store.perform_transaction(stale)
                    else:
                        result = store.cancel_transaction(stale, reason=5)
                    return ("ok", result.provider_state)
                except PaymeError as exc:
                    return ("payme_error", exc.code)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("perform", "cancel")))

    assert all(kind in {"ok", "payme_error"} for kind, _value in results)
    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.get(pk=payment_id)
        assert payment.provider_state in (STATE_CANCELLED, STATE_CANCELLED_AFTER_PERFORM)
        if payment.provider_state == STATE_CANCELLED:
            assert payment.status == Payment.Status.FAILED
            assert not PaymentAllocation.objects.filter(payment_id=payment_id).exists()
            assert not Refund.objects.filter(payment_id=payment_id).exists()
            assert not hasattr(payment, "fiscal_receipt")
        else:
            assert payment.status == Payment.Status.REFUNDED
            assert not PaymentAllocation.objects.filter(payment_id=payment_id).exists()
            refund = Refund.objects.get(payment_id=payment_id)
            assert refund.state == Refund.State.COMPLETED
            assert refund.provider == Payment.Method.PAYME
            assert refund.provider_refund_id
            # A single completion claim is the durable fiscalization outbox marker.
            assert payment.fiscal_receipt.attempts == 0


def test_concurrent_refund_requests_cannot_reserve_the_same_money_twice(tenant_a):
    from apps.finance import services as finance_services
    from apps.finance.models import Invoice, Refund
    from apps.payments.tests import _helpers as helpers
    from core.exceptions import ValidationException

    invoice = helpers.seed_open_invoice(
        tenant_a,
        number="INV-REFUND-RACE-1",
        amount_uzs="150000.00",
    )
    with schema_context(tenant_a.schema_name):
        finance_services.allocate_payment(
            payment_id=9191,
            amount_uzs=Decimal("150000.00"),
            invoice_ids=[invoice.pk],
        )
    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            with schema_context(tenant_a.schema_name):
                target = Invoice.objects.get(pk=invoice.pk)
                barrier.wait(timeout=10)
                try:
                    refund = finance_services.request_refund(
                        invoice=target,
                        payment_id=9191,
                        amount_uzs=Decimal("150000.00"),
                        provider=Payment.Method.PAYME,
                    )
                    return ("ok", refund.pk)
                except ValidationException as exc:
                    return ("validation_error", exc.code)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: run(), range(2)))

    assert sorted(kind for kind, _value in results) == ["ok", "validation_error"]
    assert [value for kind, value in results if kind == "validation_error"] == ["refund_exceeds_paid"]
    with schema_context(tenant_a.schema_name):
        assert Refund.objects.filter(invoice_id=invoice.pk, payment_id=9191).count() == 1


def test_provider_confirmed_payme_cancel_records_unallocated_refund(tenant_a):
    from apps.approvals.models import LedgerEntry
    from apps.finance.models import PaymentAllocation, Refund
    from apps.payments import services
    from apps.payments.tests import _helpers as helpers

    invoice = helpers.seed_open_invoice(
        tenant_a,
        number="INV-PAYME-UNALLOCATED-REFUND-1",
        amount_uzs="150000.00",
    )
    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.create(
            provider=Payment.Method.PAYME,
            amount_uzs=Decimal("150000.00"),
            status=Payment.Status.COMPLETED,
            idempotency_key="payme-unallocated-refund-1",
            provider_txn_id="payme-unallocated-refund-1",
            provider_state=STATE_PERFORMED,
            account_ref=invoice.number,
            metadata={"invoice_id": invoice.pk, "student_id": invoice.student_id},
        )
        cancelled = services.PaymeDBStore().cancel_transaction(payment, reason=5)
        assert cancelled.status == Payment.Status.REFUNDED
        assert not PaymentAllocation.objects.filter(payment_id=payment.pk).exists()
        refund = Refund.objects.get(payment_id=payment.pk)
        assert refund.state == Refund.State.COMPLETED
        assert refund.amount_uzs == payment.amount_uzs
        assert refund.provider_refund_id
        entry = LedgerEntry.objects.get(pk=refund.ledger_entry_id)
        assert entry.direction == LedgerEntry.Direction.OUT
        assert entry.amount_uzs == payment.amount_uzs


@override_settings(FISCALIZATION_ENABLED=False)
def test_payment_completion_skips_fiscal_outbox_when_operator_disabled(tenant_a, monkeypatch):
    from apps.payments import services
    from apps.payments.models import FiscalReceipt

    enqueued: list[tuple[int, str]] = []
    monkeypatch.setattr(
        services,
        "_enqueue_fiscalization",
        lambda payment_id, schema: enqueued.append((payment_id, schema)),
    )

    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.create(
            provider=Payment.Method.CASH,
            amount_uzs=Decimal("10.00"),
            status=Payment.Status.PENDING,
            idempotency_key="fiscalization-operator-disabled",
        )
        completed = services.mark_payment_completed(payment_id=payment.pk, auto_allocate=False)

        assert completed.status == Payment.Status.COMPLETED
        assert not FiscalReceipt.objects.filter(payment=payment).exists()
        assert enqueued == []


@override_settings(FISCALIZATION_ENABLED=False)
def test_disabled_fiscalization_tasks_do_not_seed_or_call_provider(tenant_a, monkeypatch):
    from apps.payments import services
    from apps.payments.models import FiscalReceipt
    from celery_tasks import payment_tasks

    monkeypatch.setattr(
        "infrastructure.fiscal.get_fiscal_client",
        lambda: pytest.fail("disabled fiscalization must not construct a provider client"),
    )
    enqueued: list[int] = []
    monkeypatch.setattr(
        payment_tasks.fiscalize_payment,
        "delay",
        lambda payment_id, **_kwargs: enqueued.append(payment_id),
    )

    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.create(
            provider=Payment.Method.CASH,
            amount_uzs=Decimal("10.00"),
            status=Payment.Status.COMPLETED,
            idempotency_key="disabled-fiscal-task-guard",
        )
        assert services.fiscalize_payment_body(payment.pk) is None
        assert payment_tasks.fiscalize_payment.run(payment.pk) is None
        assert payment_tasks.reconcile_fiscal_receipts_for_schema.run() == 0
        assert not FiscalReceipt.objects.filter(payment=payment).exists()

    assert payment_tasks.reconcile_fiscal_receipts.run() == 0
    assert enqueued == []


def test_fiscalization_task_acknowledges_only_after_success():
    from celery_tasks.payment_tasks import fiscalize_payment

    assert fiscalize_payment.acks_late is True
    assert fiscalize_payment.reject_on_worker_lost is True


def test_payment_completion_persists_fiscal_outbox_when_broker_publish_fails(tenant_a, monkeypatch):
    from apps.payments import services
    from apps.payments.models import FiscalReceipt

    def broker_down(*_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(services, "_enqueue_fiscalization", broker_down)
    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.create(
            provider=Payment.Method.CASH,
            amount_uzs=Decimal("10.00"),
            status=Payment.Status.PENDING,
            idempotency_key="durable-fiscal-outbox",
        )
        # robust=True prevents a post-commit broker failure from turning a
        # committed payment into an apparent HTTP failure.
        completed = services.mark_payment_completed(payment_id=payment.pk, auto_allocate=False)
        assert completed.status == Payment.Status.COMPLETED
        receipt = FiscalReceipt.objects.get(payment=payment)
        assert receipt.status == FiscalReceipt.Status.PENDING


def test_reconciler_redelivers_failed_fiscal_outbox(tenant_a, monkeypatch):
    from apps.payments.models import FiscalReceipt
    from celery_tasks import payment_tasks

    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(
        payment_tasks.fiscalize_payment,
        "delay",
        lambda payment_id, *, _schema_name: sent.append((payment_id, _schema_name)),
    )
    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.create(
            provider=Payment.Method.CASH,
            amount_uzs=Decimal("10.00"),
            status=Payment.Status.COMPLETED,
            idempotency_key="failed-fiscal-outbox",
        )
        FiscalReceipt.objects.create(payment=payment, status=FiscalReceipt.Status.FAILED)
        queued = payment_tasks.reconcile_fiscal_receipts_for_schema.run()
    assert queued == len(sent)
    assert (payment.pk, tenant_a.schema_name) in sent


def test_reconciler_seeds_missing_legacy_fiscal_outbox(tenant_a, monkeypatch):
    from celery_tasks import payment_tasks

    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(
        payment_tasks.fiscalize_payment,
        "delay",
        lambda payment_id, *, _schema_name: sent.append((payment_id, _schema_name)),
    )
    with schema_context(tenant_a.schema_name):
        payment = Payment.objects.create(
            provider=Payment.Method.CASH,
            amount_uzs=Decimal("10.00"),
            status=Payment.Status.COMPLETED,
            idempotency_key="legacy-missing-fiscal-outbox",
        )
        queued = payment_tasks.reconcile_fiscal_receipts_for_schema.run()
        assert payment.fiscal_receipt.status == payment.fiscal_receipt.Status.PENDING
    assert queued == len(sent)
    assert (payment.pk, tenant_a.schema_name) in sent


def test_branch_staff_cannot_read_or_mutate_other_branch_payments(tenant_a, user_in, as_user):
    from django.utils import timezone

    from apps.payments.tests import _helpers as helpers

    own_invoice = helpers.seed_open_invoice(
        tenant_a,
        number="INV-PAYMENT-SCOPE-OWN",
        amount_uzs="100.00",
    )
    other_invoice = helpers.seed_open_invoice(
        tenant_a,
        number="INV-PAYMENT-SCOPE-OTHER",
        amount_uzs="200.00",
    )
    with schema_context(tenant_a.schema_name):
        own_branch = own_invoice.student.branch
        own_payment = Payment.objects.create(
            provider=Payment.Method.CLICK,
            amount_uzs=Decimal("100.00"),
            status=Payment.Status.COMPLETED,
            idempotency_key="payment-scope-own",
            account_ref=own_invoice.number,
            paid_at=timezone.now(),
            metadata={"invoice_id": own_invoice.pk, "student_id": own_invoice.student_id},
        )
        other_payment = Payment.objects.create(
            provider=Payment.Method.CLICK,
            amount_uzs=Decimal("200.00"),
            status=Payment.Status.COMPLETED,
            idempotency_key="payment-scope-other",
            account_ref=other_invoice.number,
            paid_at=timezone.now(),
            metadata={"invoice_id": other_invoice.pk, "student_id": other_invoice.student_id},
        )

    accountant = user_in(tenant_a, roles=["accountant"], branch=own_branch)
    client = as_user(tenant_a, accountant)

    listing = client.get("/api/v1/payments/")
    assert listing.status_code == 200
    assert listing.json()["pagination"]["total"] == 1
    assert listing.json()["data"][0]["id"] == own_payment.pk
    assert client.get(f"/api/v1/payments/{other_payment.pk}/").status_code == 403
    assert (
        client.post(
            "/api/v1/payments/checkout/",
            {"invoice": other_invoice.pk, "provider": "payme"},
            format="json",
        ).status_code
        == 403
    )
    assert client.post(f"/api/v1/payments/{other_payment.pk}/refund/", {}).status_code == 403
    assert (
        client.post(
            f"/api/v1/payments/{own_payment.pk}/allocate/",
            {"allocations": [{"invoice": other_invoice.pk, "amount": "1.00"}]},
            format="json",
        ).status_code
        == 403
    )
    reconciliation = client.get(
        "/api/v1/payments/reconciliation/",
        {"date": timezone.localdate().isoformat()},
    )
    assert reconciliation.status_code == 200
    assert reconciliation.json()["data"]["total_paid_uzs"] == "100.00"


def test_refund_api_returns_202_and_requires_separate_approver(tenant_a, user_in, as_user):
    from apps.finance.models import Refund
    from apps.payments import services
    from apps.payments.tests import _helpers as helpers
    from core.permissions import Role

    helpers.seed_provider_configs(tenant_a)
    invoice = helpers.seed_open_invoice(
        tenant_a,
        number="INV-REFUND-API-1",
        amount_uzs="150000.00",
    )
    tenant = tenant_a
    branch = invoice.student.branch
    requester = user_in(tenant, roles=[Role.ACCOUNTANT], branch=branch)
    approver = user_in(tenant, roles=[Role.HEAD_OF_DEPT], branch=branch)
    requester_client = as_user(tenant, requester)
    approver_client = as_user(tenant, approver)

    with schema_context(tenant.schema_name):
        payment = services.process_click_complete(
            payload={
                "click_trans_id": "click-refund-api",
                "merchant_trans_id": invoice.number,
                "amount": str(invoice.total_uzs),
            },
            invoice=invoice,
        )

    response = requester_client.post(
        f"/api/v1/payments/{payment.pk}/refund/",
        {"reason": "customer request"},
        format="json",
    )
    assert response.status_code == 202, response.content
    request_data = response.json()["data"]["refund_request"]
    assert request_data["state"] == Refund.State.REQUESTED

    listing = requester_client.get("/api/v1/finance/refunds/")
    assert listing.status_code == 200
    assert listing.json()["pagination"]["total"] == 1
    refund_id = request_data["id"]

    assert requester_client.post(f"/api/v1/finance/refunds/{refund_id}/approve/", {}).status_code == 403
    approved = approver_client.post(f"/api/v1/finance/refunds/{refund_id}/approve/", {})
    assert approved.status_code == 200, approved.content
    assert approved.json()["data"]["state"] == Refund.State.APPROVED
    with schema_context(tenant.schema_name):
        payment.refresh_from_db()
        refund = Refund.objects.get(pk=refund_id)
        assert payment.status == Payment.Status.COMPLETED
        assert refund.ledger_entry_id is None
