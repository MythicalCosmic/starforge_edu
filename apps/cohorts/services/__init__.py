"""Cohort write services: enrollment + mid-term moves that preserve history
(TASKS §8).

Kept as module-level domain functions (not just the layered service class) because
the finance auto-issue receiver and several tests import them directly:
``from apps.cohorts.services import enroll_student_in_cohort, move_student``.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.cohorts.models import Cohort, CohortMembership
from apps.cohorts.signals import cohort_member_moved
from core.exceptions import ConflictException, ValidationException
from core.utils import current_schema


def _active_count(cohort: Cohort) -> int:
    return cohort.memberships.filter(end_date__isnull=True).count()


@transaction.atomic
def enroll_student_in_cohort(*, cohort: Cohort, student, start_date=None) -> CohortMembership:
    if cohort.is_archived:
        raise ValidationException(_("Cohort is archived."), code="cohort_archived")
    if student.branch_id != cohort.branch_id:
        raise ValidationException(
            _("Student belongs to a different branch than this cohort."),
            code="student_branch_mismatch",
        )
    if CohortMembership.objects.filter(cohort=cohort, student=student, end_date__isnull=True).exists():
        raise ValidationException(_("Student is already active in this cohort."), code="already_enrolled")
    try:
        with transaction.atomic():
            membership = CohortMembership.objects.create(
                cohort=cohort, student=student, start_date=start_date or timezone.now().date()
            )
    except IntegrityError as exc:
        # Lost the read-then-write race against a concurrent enroll: the partial
        # unique constraint (one_active_membership_per_cohort_student) rejected
        # the second writer. Surface as 409, not a 500.
        raise ConflictException(
            _("Student is already active in this cohort."), code="already_enrolled"
        ) from exc
    # Multi-cohort enrollment IS a supported feature (a student may take e.g. English AND
    # Math simultaneously — see apps/schedule/tests test_student_sees_lessons_from_both_
    # active_cohorts, and attendance/content scoping joins active memberships plural). So
    # each cohort keeps its own active CohortMembership and bills per its own fee schedule
    # (auto_issue_on_enrollment). `current_cohort` is the student's PRIMARY cohort: set it
    # on the FIRST enrollment but do NOT let a secondary enroll silently reassign it (a
    # MOVE, via move_student, is the explicit way to change the primary). This keeps the
    # primary stable for dashboards/reports while allowing multiple active memberships.
    if student.current_cohort_id is None:
        student.current_cohort = cohort
        student.save(update_fields=["current_cohort", "updated_at"])

    schema = current_schema()
    transaction.on_commit(
        lambda: cohort_member_moved.send(
            sender=CohortMembership,
            student_id=student.pk,
            to_cohort_id=cohort.pk,
            schema_name=schema,
        )
    )
    return membership


@transaction.atomic
def move_student(*, student, to_cohort: Cohort, reason: str = "", actor=None) -> dict[str, Any]:
    """End-date the student's active memberships and open a new one in
    `to_cohort`. History is retained; over-capacity is a soft warning, never a
    block (Lane F contract). The student row is locked (F2-6) so two concurrent
    moves can't each end-date the original and open a new one, leaving the student
    in two active cohorts."""
    student = type(student).objects.select_for_update().get(pk=student.pk)
    if to_cohort.is_archived:
        raise ValidationException(_("Target cohort is archived."), code="cohort_archived")
    if student.branch_id != to_cohort.branch_id:
        raise ValidationException(
            _("Student belongs to a different branch than the target cohort."),
            code="student_branch_mismatch",
        )

    today = timezone.now().date()
    CohortMembership.objects.filter(student=student, end_date__isnull=True).update(
        end_date=today, moved_reason=reason
    )
    membership = CohortMembership.objects.create(cohort=to_cohort, student=student, start_date=today)
    student.current_cohort = to_cohort
    student.save(update_fields=["current_cohort", "updated_at"])

    over_capacity = to_cohort.capacity is not None and _active_count(to_cohort) > to_cohort.capacity

    schema = current_schema()
    transaction.on_commit(
        lambda: cohort_member_moved.send(
            sender=CohortMembership,
            student_id=student.pk,
            to_cohort_id=to_cohort.pk,
            schema_name=schema,
        )
    )
    return {"membership": membership, "over_capacity": over_capacity}
