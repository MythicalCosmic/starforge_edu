"""Payments read selectors (D3-B-10). Reads only; eager-loaded + scoped."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Q, QuerySet, Subquery

from apps.payments.models import Payment


def payments_qs() -> QuerySet[Payment]:
    return Payment.objects.select_related("payer", "cashier_shift").order_by("-created_at")


def payments_for_branches(queryset: QuerySet[Payment], *, branch_ids: set[int]) -> QuerySet[Payment]:
    """Limit the staff payment log to transactions belonging to their branches.

    ``Payment`` deliberately has no direct invoice FK. Provider rows carry the
    canonical invoice number in indexed ``account_ref``; cash rows also carry a
    drawer branch, and older/manual rows can be recovered through the finance
    allocation spine. Keep all three paths in one selector so list, detail and
    reconciliation cannot drift into different authorization rules.
    """
    from apps.finance.models import Invoice, PaymentAllocation

    invoice_numbers = Invoice.objects.filter(student__branch_id__in=branch_ids).values("number")
    allocation_payment_ids = PaymentAllocation.objects.filter(
        invoice__student__branch_id__in=branch_ids
    ).values("payment_id")
    return queryset.filter(
        Q(cashier_shift__branch_id__in=branch_ids)
        | Q(account_ref__in=Subquery(invoice_numbers))
        | Q(pk__in=Subquery(allocation_payment_ids))
    ).distinct()


def reconciliation(*, on: date, branch_ids: set[int] | None = None) -> dict[str, Any]:
    """Payments completed on ``on`` vs the amount finance allocated against them.

    Mismatch = a completed payment whose allocated total != its amount. Finance's
    ``PaymentAllocation`` carries a soft ``payment_id`` (BigInteger, not an FK —
    Lane A decision), so we sum it via a lazy query and tolerate finance absent.
    """
    completed_qs = Payment.objects.filter(status=Payment.Status.COMPLETED, paid_at__date=on)
    if branch_ids is not None:
        completed_qs = payments_for_branches(completed_qs, branch_ids=branch_ids)
    completed = list(completed_qs.values("id", "amount_uzs", "provider", "allocation_status"))
    payment_ids = [p["id"] for p in completed]
    from apps.finance.models import PaymentAllocation

    allocated: dict[int, Decimal] = {}
    rows = PaymentAllocation.objects.filter(payment_id__in=payment_ids).values_list(
        "payment_id", "amount_uzs"
    )
    for pid, amt in rows:
        allocated[pid] = allocated.get(pid, Decimal("0")) + (amt or Decimal("0"))

    total_paid = sum((p["amount_uzs"] for p in completed), Decimal("0"))
    total_allocated = sum(allocated.values(), Decimal("0"))
    mismatches = [
        {
            "payment_id": p["id"],
            "amount_uzs": str(p["amount_uzs"]),
            "allocated_uzs": str(allocated.get(p["id"], Decimal("0"))),
            "allocation_status": p["allocation_status"],
        }
        for p in completed
        if allocated.get(p["id"], Decimal("0")) != p["amount_uzs"]
    ]
    by_provider: dict[str, Decimal] = {}
    for p in completed:
        by_provider[p["provider"]] = by_provider.get(p["provider"], Decimal("0")) + p["amount_uzs"]
    return {
        "date": on.isoformat(),
        "total_paid_uzs": str(total_paid),
        "total_allocated_uzs": str(total_allocated),
        "by_provider": {k: str(v) for k, v in by_provider.items()},
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }
