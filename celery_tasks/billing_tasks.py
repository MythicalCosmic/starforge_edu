"""Billing beat tasks (D3-E-5).

Nightly: for each active Center, snapshot usage (students/storage/AI tokens) and
evaluate subscription state flips (trialing/active/past_due → past_due/suspended).

Fan-out pattern mirrors attendance/assignment beat tasks: the public dispatcher
iterates active Centers; the per-center body runs inside that Center's tenant
schema for the tenant-scoped reads (student count, storage bytes, AI tokens) and
hops to the public schema for the Subscription / UsageSnapshot writes.

Idempotent: UsageSnapshot is unique per (center, date) and updated in place;
state flips are no-ops when already in the target status.
"""

from __future__ import annotations

import logging

from django.utils import timezone
from django_tenants.utils import schema_context

from config.celery import app

logger = logging.getLogger("starforge.billing")


def _active_centers():
    from apps.tenancy.models import Center

    return list(Center.objects.filter(is_active=True))


@app.task
def run_nightly_metering() -> int:
    """Public dispatcher: meter + evaluate every active Center. Returns count."""
    centers = _active_centers()
    for center in centers:
        meter_center(center_id=center.pk)
    return len(centers)


def meter_center(*, center_id: int) -> None:
    """Snapshot one Center's usage and evaluate its subscription state.

    Separated from the dispatcher so tests can drive a single center directly.
    The public-schema reads/writes (Center, UsageSnapshot, Subscription) are
    wrapped in an explicit public schema_context so this is correct no matter
    which schema is active when the task body runs; tenant reads (student count,
    storage, AI tokens) hop into the tenant schema individually.
    """
    from django_tenants.utils import get_public_schema_name

    from apps.billing.models import Subscription, UsageSnapshot
    from apps.billing.services import apply_state_flip, evaluate_subscription_state
    from apps.tenancy.models import Center

    with schema_context(get_public_schema_name()):
        center = Center.objects.filter(pk=center_id, is_active=True).first()
    if center is None:
        return

    today = timezone.now().date()
    students_count = _students_count(center.schema_name)
    storage_bytes = _storage_bytes(center.schema_name)
    ai_tokens = _ai_tokens(center.schema_name)

    with schema_context(get_public_schema_name()):
        # Snapshot write lives on the public schema (UsageSnapshot is public).
        UsageSnapshot.objects.update_or_create(
            center=center,
            date=today,
            defaults={
                "students_count": students_count,
                "storage_bytes": storage_bytes,
                "ai_tokens_used": ai_tokens,
            },
        )
        sub = Subscription.objects.select_related("plan", "center").filter(center=center).first()

    if sub is None:
        return
    new_status = evaluate_subscription_state(subscription=sub)
    if new_status is not None:
        apply_state_flip(subscription=sub, new_status=new_status)


def _students_count(schema_name: str) -> int:
    # Seat-consuming students (enrolled OR active) — matches
    # apps.billing.services._active_student_count so the meter and the plan-limit
    # enforcement count the same population.
    from apps.students.models import StudentProfile

    with schema_context(schema_name):
        return StudentProfile.objects.filter(
            status__in=(StudentProfile.Status.ENROLLED, StudentProfile.Status.ACTIVE)
        ).count()


def _storage_bytes(schema_name: str) -> int:
    # D2-E published interface: apps.content.selectors.storage_used_bytes() (the
    # actual published name — WORKLOG Day-2 Lane E). Degrade to 0 if unavailable.
    try:
        from apps.content.selectors import storage_used_bytes
    except Exception:
        return 0
    with schema_context(schema_name):
        try:
            return int(storage_used_bytes())
        except Exception:
            logger.exception("storage_used_bytes failed", extra={"schema": schema_name})
            return 0


def _ai_tokens(schema_name: str) -> int:
    # D3-E-6 stub: apps.ai.selectors.tokens_used_current_month() returns 0 until
    # D4-A wires the real implementation (declared additive cross-lane touch).
    try:
        from apps.ai.selectors import tokens_used_current_month
    except Exception:
        return 0
    with schema_context(schema_name):
        try:
            return int(tokens_used_current_month())
        except Exception:
            return 0
