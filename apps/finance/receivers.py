"""Finance signal receivers (D3-A-3): auto-issue an invoice on enrollment.

The auto-issue trigger is the cohorts enrollment signal. Day-1 published
`apps.cohorts.signals.cohort_member_moved` (fires on `move_student`). The
INITIAL `enroll_student_in_cohort` call does NOT yet emit a signal — see
integration_needed: a `student_enrolled` emit must be added to
`apps.cohorts.services.enroll_student_in_cohort` (one `transaction.on_commit`
line) and connected below. Until then this receiver fires on cohort moves, which
exercises the dedupe + materialization path end to end.

The receiver body is deliberately thin: it enqueues nothing heavy synchronously;
`auto_issue_on_enrollment` is idempotent (dedupe on (student, fee_schedule,
period)) so a re-fired signal creates no duplicate invoice.
"""

from __future__ import annotations

import logging

from django.dispatch import receiver

from apps.cohorts.signals import cohort_member_moved

logger = logging.getLogger("starforge.finance")


@receiver(cohort_member_moved, dispatch_uid="finance.auto_issue_on_enrollment")
def on_cohort_member_moved(sender, *, student_id, to_cohort_id, schema_name="", **kwargs) -> None:
    """Issue (idempotently) the matching fee-schedule invoice when a student lands
    in a cohort. Runs in the active tenant schema (the signal is emitted inside
    `transaction.on_commit`, so the membership row is committed)."""
    from apps.finance.services import auto_issue_on_enrollment

    try:
        auto_issue_on_enrollment(student_id=student_id, cohort_id=to_cohort_id)
    except Exception:  # never let a notification/billing hiccup break enrollment
        logger.exception(
            "auto_issue_on_enrollment failed student=%s cohort=%s schema=%s",
            student_id,
            to_cohort_id,
            schema_name,
        )
