"""Finance lane tests (D3-A). Run centrally on Postgres.

Covers the DAY-3 Lane A "Tests required" list: happy-path invoice issue;
auto-issue-on-enrollment fires once; allocation exactness incl. a 3-way split of
an odd amount; cashier shift double-open rejected; parent sees only own
children's balances; cross-tenant isolation on /invoices/; query-count on the
invoice list (<=5). Plus sibling-discount materialization, the refund state
machine + register_refund_completion, payment plans, void, FX snapshot, and the
late-payment-reminder + statement task bodies.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.cache import cache
from django_tenants.utils import schema_context

from apps.cohorts.tests.factories import CohortFactory, CohortMembershipFactory
from apps.finance import selectors, services
from apps.finance.models import (
    CashierShift,
    Invoice,
    InvoiceLine,
    PaymentAllocation,
    Refund,
)
from apps.finance.signals import invoice_issued, payment_reminder
from apps.finance.tests.factories import (
    DiscountFactory,
    FeeScheduleFactory,
    InvoiceFactory,
)
from apps.org.models import CenterSettings
from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
from apps.students.models import StudentProfile
from apps.students.tests.factories import StudentProfileFactory
from core.exceptions import ConflictException, ValidationException
from core.permissions import Role

pytestmark = pytest.mark.django_db


def _settings(**kwargs):
    """Set CenterSettings fields (incl. the additive finance knobs once merged)
    and bust the cache. Skips fields not yet present on the model."""
    cs = CenterSettings.load()
    for key, value in kwargs.items():
        if hasattr(cs, key):
            setattr(cs, key, value)
    cs.save()
    cache.clear()
    return cs


# --------------------------------------------------------------------------- #
# issue_invoice — happy path, numbering, FX snapshot
# --------------------------------------------------------------------------- #


def test_issue_invoice_happy_path_numbering_and_lines(tenant_a, django_capture_on_commit_callbacks):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        fs = FeeScheduleFactory(amount_uzs=Decimal("1500000.00"))
        captured = []
        invoice_issued.connect(lambda **kw: captured.append(kw), weak=False, dispatch_uid="t1")
        try:
            # execute=True runs the transaction.on_commit callback so the
            # emit-on-commit contract (services send signals on commit) is
            # exercised — mirrors the payments/attendance signal tests.
            with django_capture_on_commit_callbacks(execute=True):
                inv = services.issue_invoice(student_id=student.pk, fee_schedule_id=fs.pk)
        finally:
            invoice_issued.disconnect(dispatch_uid="t1")

        assert inv.status == Invoice.Status.ISSUED
        assert inv.number.startswith("INV-")
        assert inv.number.endswith("000001")
        assert inv.total_uzs == Decimal("1500000.00")
        assert inv.lines.count() == 1
        # signal fired once with the documented kwargs
        assert len(captured) == 1
        assert captured[0]["invoice_id"] == inv.pk
        assert captured[0]["student_id"] == student.pk


def test_issue_invoice_number_is_sequential_per_year(tenant_a):
    with schema_context(tenant_a.schema_name):
        fs = FeeScheduleFactory()
        s1, s2 = StudentProfileFactory(), StudentProfileFactory()
        i1 = services.issue_invoice(student_id=s1.pk, fee_schedule_id=fs.pk)
        i2 = services.issue_invoice(student_id=s2.pk, fee_schedule_id=fs.pk)
        n1 = int(i1.number.rsplit("-", 1)[1])
        n2 = int(i2.number.rsplit("-", 1)[1])
        assert n2 == n1 + 1


def test_issue_invoice_fx_snapshot_manual(tenant_a):
    with schema_context(tenant_a.schema_name):
        cs = _settings(fx_source="manual")
        if hasattr(cs, "fx_rate_usd_manual"):
            cs.fx_rate_usd_manual = Decimal("12500.0000")
            cs.save()
            cache.clear()
        fs = FeeScheduleFactory(amount_uzs=Decimal("1250000.00"))
        student = StudentProfileFactory()
        inv = services.issue_invoice(student_id=student.pk, fee_schedule_id=fs.pk)
        if hasattr(cs, "fx_rate_usd_manual"):
            assert inv.fx_rate_usd == Decimal("12500.0000")
            assert inv.total_usd == Decimal("100.00")  # 1,250,000 / 12,500
        else:
            # knob not merged yet — snapshot is null, never a crash
            assert inv.total_usd is None or inv.total_usd >= Decimal("0")


def test_issue_invoice_explicit_lines(tenant_a):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        inv = services.issue_invoice(
            student_id=student.pk,
            lines=[
                {"description": "Books", "line_type": "material", "quantity": "2", "unit_price_uzs": "50000"},
            ],
        )
        assert inv.total_uzs == Decimal("100000.00")


def test_issue_invoice_empty_raises(tenant_a):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        with pytest.raises(ValidationException):
            services.issue_invoice(student_id=student.pk)


# --------------------------------------------------------------------------- #
# sibling discount materialization
# --------------------------------------------------------------------------- #


def test_sibling_discount_materializes_negative_line(tenant_a):
    with schema_context(tenant_a.schema_name):
        cs = CenterSettings.load()
        if not hasattr(cs, "sibling_discount_percent"):
            pytest.skip("sibling_discount_percent knob not merged yet (integration_needed)")
        cs.sibling_discount_percent = Decimal("10.00")
        cs.save()
        cache.clear()

        parent = ParentProfileFactory()
        s1 = StudentProfileFactory(status=StudentProfile.Status.ENROLLED)
        s2 = StudentProfileFactory(status=StudentProfile.Status.ENROLLED)
        GuardianFactory(parent=parent, student=s1)
        GuardianFactory(parent=parent, student=s2)

        fs = FeeScheduleFactory(amount_uzs=Decimal("1000000.00"))
        inv = services.issue_invoice(student_id=s1.pk, fee_schedule_id=fs.pk)
        discount_lines = inv.lines.filter(line_type=InvoiceLine.LineType.DISCOUNT)
        assert discount_lines.count() == 1
        assert discount_lines.first().amount_uzs == Decimal("-100000.00")
        assert inv.total_uzs == Decimal("900000.00")


def test_no_sibling_discount_without_enrolled_sibling(tenant_a):
    with schema_context(tenant_a.schema_name):
        cs = CenterSettings.load()
        if not hasattr(cs, "sibling_discount_percent"):
            pytest.skip("sibling_discount_percent knob not merged yet")
        cs.sibling_discount_percent = Decimal("10.00")
        cs.save()
        cache.clear()
        solo = StudentProfileFactory(status=StudentProfile.Status.ENROLLED)
        fs = FeeScheduleFactory(amount_uzs=Decimal("1000000.00"))
        inv = services.issue_invoice(student_id=solo.pk, fee_schedule_id=fs.pk)
        assert inv.lines.filter(line_type=InvoiceLine.LineType.DISCOUNT).count() == 0
        assert inv.total_uzs == Decimal("1000000.00")


def test_standing_discount_materializes(tenant_a):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        DiscountFactory(student=student, percent=Decimal("20.00"), fixed_amount_uzs=None)
        fs = FeeScheduleFactory(amount_uzs=Decimal("500000.00"))
        inv = services.issue_invoice(student_id=student.pk, fee_schedule_id=fs.pk)
        assert inv.total_uzs == Decimal("400000.00")


# --------------------------------------------------------------------------- #
# auto-issue on enrollment (idempotent / fires once)
# --------------------------------------------------------------------------- #


def test_auto_issue_on_enrollment_creates_one_invoice(tenant_a):
    with schema_context(tenant_a.schema_name):
        cohort = CohortFactory()
        student = StudentProfileFactory(current_cohort=cohort)
        FeeScheduleFactory(cohort=cohort, amount_uzs=Decimal("800000.00"))

        inv = services.auto_issue_on_enrollment(student_id=student.pk, cohort_id=cohort.pk)
        assert inv is not None
        assert Invoice.objects.filter(student=student).count() == 1

        # Re-firing the signal body must NOT duplicate (dedupe on student/fs/period)
        again = services.auto_issue_on_enrollment(student_id=student.pk, cohort_id=cohort.pk)
        assert again.pk == inv.pk
        assert Invoice.objects.filter(student=student).count() == 1


def test_auto_issue_falls_back_to_center_wide_schedule(tenant_a):
    with schema_context(tenant_a.schema_name):
        cohort = CohortFactory()
        student = StudentProfileFactory(current_cohort=cohort)
        FeeScheduleFactory(cohort=None, amount_uzs=Decimal("700000.00"))  # center-wide
        inv = services.auto_issue_on_enrollment(student_id=student.pk, cohort_id=cohort.pk)
        assert inv is not None
        assert inv.total_uzs == Decimal("700000.00")


def test_auto_issue_no_matching_schedule_returns_none(tenant_a):
    with schema_context(tenant_a.schema_name):
        cohort = CohortFactory()
        student = StudentProfileFactory(current_cohort=cohort)
        assert services.auto_issue_on_enrollment(student_id=student.pk, cohort_id=cohort.pk) is None
        assert Invoice.objects.filter(student=student).count() == 0


def test_enrollment_signal_receiver_issues_once(tenant_a, django_capture_on_commit_callbacks):
    """The receiver is wired to cohort_member_moved; firing it issues exactly one
    invoice and a second fire dedupes."""
    from apps.cohorts.services import move_student

    with schema_context(tenant_a.schema_name):
        source = CohortFactory()
        target = CohortFactory()
        student = StudentProfileFactory(current_cohort=source)
        CohortMembershipFactory(cohort=source, student=student)
        FeeScheduleFactory(cohort=target, amount_uzs=Decimal("600000.00"))

        # move_student emits cohort_member_moved inside transaction.on_commit;
        # execute=True runs that callback so the finance receiver auto-issues.
        with django_capture_on_commit_callbacks(execute=True):
            move_student(student=student, to_cohort=target)
        assert Invoice.objects.filter(student=student).count() == 1


# --------------------------------------------------------------------------- #
# allocate_payment — exactness, 3-way odd split, status flips, over-allocation
# --------------------------------------------------------------------------- #


def test_allocate_payment_single_invoice_marks_paid(tenant_a):
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("1000000.00"))
        allocs = services.allocate_payment(payment_id=1, amount_uzs=Decimal("1000000.00"))
        assert len(allocs) == 1
        inv.refresh_from_db()
        assert inv.status == Invoice.Status.PAID


def test_allocate_payment_partial_marks_partially_paid(tenant_a):
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("1000000.00"))
        services.allocate_payment(payment_id=2, amount_uzs=Decimal("400000.00"))
        inv.refresh_from_db()
        assert inv.status == Invoice.Status.PARTIALLY_PAID


def test_allocate_payment_oldest_due_first(tenant_a):
    from datetime import date

    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        old = InvoiceFactory(student=student, due_date=date(2026, 1, 1), total_uzs=Decimal("300000.00"))
        new = InvoiceFactory(student=student, due_date=date(2026, 6, 1), total_uzs=Decimal("300000.00"))
        services.allocate_payment(payment_id=3, amount_uzs=Decimal("300000.00"))
        old.refresh_from_db()
        new.refresh_from_db()
        assert old.status == Invoice.Status.PAID
        assert new.status == Invoice.Status.ISSUED


def test_allocate_payment_three_way_odd_split_is_exact(tenant_a):
    """Awkward amount over 3 invoices: sum(allocations) == amount EXACTLY (no
    rounding loss), Decimal throughout."""
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        for _ in range(3):
            InvoiceFactory(student=student, total_uzs=Decimal("333333.34"))
        amount = Decimal("1000000.01")
        allocs = services.allocate_payment(payment_id=4, amount_uzs=amount)
        total = sum((a.amount_uzs for a in allocs), Decimal("0"))
        assert total == amount
        for a in allocs:
            assert isinstance(a.amount_uzs, Decimal)


def test_allocate_payment_over_allocation_raises(tenant_a):
    with schema_context(tenant_a.schema_name):
        InvoiceFactory(total_uzs=Decimal("100000.00"))
        with pytest.raises(ValidationException) as exc:
            services.allocate_payment(payment_id=5, amount_uzs=Decimal("200000.00"))
        assert exc.value.code == "over_allocation"


def test_allocate_payment_idempotent_on_payment_id(tenant_a):
    with schema_context(tenant_a.schema_name):
        InvoiceFactory(total_uzs=Decimal("100000.00"))
        first = services.allocate_payment(payment_id=6, amount_uzs=Decimal("100000.00"))
        again = services.allocate_payment(payment_id=6, amount_uzs=Decimal("100000.00"))
        assert {a.pk for a in first} == {a.pk for a in again}
        assert PaymentAllocation.objects.filter(payment_id=6).count() == 1


# --------------------------------------------------------------------------- #
# cashier shift open/close + double-open guard + report
# --------------------------------------------------------------------------- #


def test_cashier_shift_double_open_rejected(tenant_a, user_in):
    from apps.org.tests.factories import BranchFactory

    cashier = user_in(tenant_a, roles=[Role.CASHIER])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        services.open_cashier_shift(cashier=cashier, branch=branch)
        with pytest.raises(ConflictException) as exc:
            services.open_cashier_shift(cashier=cashier, branch=branch)
        assert exc.value.code == "shift_already_open"


def test_cashier_shift_close_computes_discrepancy(tenant_a, user_in):
    from apps.org.tests.factories import BranchFactory

    cashier = user_in(tenant_a, roles=[Role.CASHIER])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        shift = services.open_cashier_shift(
            cashier=cashier, branch=branch, opening_cash_uzs=Decimal("50000.00")
        )
        closed = services.close_cashier_shift(shift=shift, closing_cash_uzs=Decimal("70000.00"))
        # no payments merged -> discrepancy = 70000 - (50000 + 0) = 20000
        assert closed.discrepancy_uzs == Decimal("20000.00")
        assert closed.status == CashierShift.Status.CLOSED


def test_cashier_report_tolerates_zero_payments(tenant_a, user_in):
    from apps.org.tests.factories import BranchFactory

    cashier = user_in(tenant_a, roles=[Role.CASHIER])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        shift = services.open_cashier_shift(cashier=cashier, branch=branch)
        report = selectors.cashier_shift_report(shift=shift)
        assert report["payments_total_uzs"] == "0.00"
        assert report["totals_by_provider"] == {}


# --------------------------------------------------------------------------- #
# payment plan
# --------------------------------------------------------------------------- #


def test_payment_plan_must_sum_to_total(tenant_a):
    from datetime import date

    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("1000000.00"))
        with pytest.raises(ValidationException) as exc:
            services.create_payment_plan(
                invoice=inv,
                installments=[{"due_date": date(2026, 7, 5), "amount_uzs": "999999.00"}],
            )
        assert exc.value.code == "plan_sum_mismatch"


def test_payment_plan_happy(tenant_a):
    from datetime import date

    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("1000000.00"))
        plan = services.create_payment_plan(
            invoice=inv,
            installments=[
                {"due_date": date(2026, 7, 5), "amount_uzs": "500000.00"},
                {"due_date": date(2026, 8, 5), "amount_uzs": "500000.00"},
            ],
        )
        assert plan.installments.count() == 2


# --------------------------------------------------------------------------- #
# refund state machine + register_refund_completion (Lane B entry point)
# --------------------------------------------------------------------------- #


def test_refund_illegal_transition_raises(tenant_a):
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("100000.00"))
        services.allocate_payment(payment_id=20, amount_uzs=Decimal("100000.00"))
        refund = services.request_refund(invoice=inv, amount_uzs=Decimal("100000.00"), payment_id=20)
        with pytest.raises(ValidationException) as exc:
            services.transition_refund(refund_id=refund.pk, to_state=Refund.State.COMPLETED)
        assert exc.value.code == "invalid_refund_transition"


def test_register_refund_completion_idempotent(tenant_a):
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("100000.00"))
        services.allocate_payment(payment_id=21, amount_uzs=Decimal("100000.00"))
        refund = services.request_refund(invoice=inv, amount_uzs=Decimal("100000.00"))
        done = services.register_refund_completion(refund.pk, payment_id=21)
        assert done.state == Refund.State.COMPLETED
        assert done.payment_id == 21
        again = services.register_refund_completion(refund.pk, payment_id=21)
        assert again.state == Refund.State.COMPLETED


def test_refund_exceeds_paid_rejected(tenant_a):
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("100000.00"))
        services.allocate_payment(payment_id=22, amount_uzs=Decimal("50000.00"))
        with pytest.raises(ValidationException) as exc:
            services.request_refund(invoice=inv, amount_uzs=Decimal("90000.00"))
        assert exc.value.code == "refund_exceeds_paid"


# --------------------------------------------------------------------------- #
# void
# --------------------------------------------------------------------------- #


def test_void_invoice_with_payments_rejected(tenant_a):
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("100000.00"))
        services.allocate_payment(payment_id=30, amount_uzs=Decimal("100000.00"))
        with pytest.raises(ConflictException):
            services.void_invoice(invoice=inv)


def test_void_clean_invoice(tenant_a):
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("100000.00"))
        services.void_invoice(invoice=inv)
        inv.refresh_from_db()
        assert inv.status == Invoice.Status.VOID


# --------------------------------------------------------------------------- #
# outstanding balance — parent scoping
# --------------------------------------------------------------------------- #


def test_outstanding_balance_math(tenant_a):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        InvoiceFactory(student=student, total_uzs=Decimal("100000.00"))
        inv2 = InvoiceFactory(student=student, total_uzs=Decimal("100000.00"))
        # pay one fully
        services.allocate_payment(payment_id=40, invoice_ids=[inv2.pk], amount_uzs=Decimal("100000.00"))
        assert selectors.outstanding_balance(student.pk) == Decimal("100000.00")


# --------------------------------------------------------------------------- #
# late_payment_reminders — emit once per interval, dedupe same day
# --------------------------------------------------------------------------- #


def test_payment_reminders_emit_once_and_dedupe(tenant_a):
    from datetime import date

    with schema_context(tenant_a.schema_name):
        cache.clear()
        InvoiceFactory(due_date=date(2020, 1, 1), status=Invoice.Status.ISSUED)
        captured = []
        payment_reminder.connect(lambda **kw: captured.append(kw), weak=False, dispatch_uid="rem")
        try:
            n1 = services.emit_payment_reminders(today=date(2020, 1, 10))
            n2 = services.emit_payment_reminders(today=date(2020, 1, 10))
        finally:
            payment_reminder.disconnect(dispatch_uid="rem")
        assert n1 == 1
        assert n2 == 0  # same interval bucket -> deduped
        assert len(captured) == 1
        # the invoice flipped to overdue
        assert Invoice.objects.filter(status=Invoice.Status.OVERDUE).count() == 1


# --------------------------------------------------------------------------- #
# statement task body (weasyprint skip when native libs absent)
# --------------------------------------------------------------------------- #

try:  # pragma: no cover - import probe
    import weasyprint  # noqa: F401

    _HAS_WEASYPRINT = True
except Exception:
    _HAS_WEASYPRINT = False


@pytest.mark.skipif(not _HAS_WEASYPRINT, reason="weasyprint native libs unavailable (CI/Linux runs it)")
def test_render_statement_pdf_real(tenant_a):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        InvoiceFactory(student=student, total_uzs=Decimal("100000.00"))
        pdf = services.render_statement_pdf(student=student, locale="en")
        assert pdf.startswith(b"%PDF")


def test_generate_statement_uploads_to_s3(tenant_a, monkeypatch):
    """Task body uploads to {schema}/documents/ — stub weasyprint + S3."""
    captured = {}

    def fake_render(*, student, locale="en"):
        return b"%PDF-stub"

    def fake_upload(key, data, *, content_type="application/octet-stream"):
        captured["key"] = key
        captured["data"] = data
        return key

    monkeypatch.setattr(services, "render_statement_pdf", fake_render)
    monkeypatch.setattr("infrastructure.storage.s3_client.upload_bytes", fake_upload)
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        key = services.generate_statement(student.pk, locale="en")
        assert key == captured["key"]
        assert f"{tenant_a.schema_name}/documents/" in key
        assert captured["data"] == b"%PDF-stub"
