"""Cohort write services: enrollment + mid-term moves that preserve history
(TASKS §8)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.cohorts.models import Cohort, CohortMembership
from apps.cohorts.signals import cohort_member_moved
from core.exceptions import ValidationException
from core.utils import current_schema


def _active_count(cohort: Cohort) -> int:
    return cohort.memberships.filter(end_date__isnull=True).count()


@transaction.atomic
def enroll_student_in_cohort(*, cohort: Cohort, student, start_date=None) -> CohortMembership:
    if cohort.is_archived:
        raise ValidationException(_("Cohort is archived."), code="cohort_archived")
    if CohortMembership.objects.filter(cohort=cohort, student=student, end_date__isnull=True).exists():
        raise ValidationException(_("Student is already active in this cohort."), code="already_enrolled")
    membership = CohortMembership.objects.create(
        cohort=cohort, student=student, start_date=start_date or timezone.now().date()
    )
    student.current_cohort = cohort
    student.save(update_fields=["current_cohort", "updated_at"])
    return membership


@transaction.atomic
def move_student(*, student, to_cohort: Cohort, reason: str = "", actor=None) -> dict[str, Any]:
    """End-date the student's active memberships and open a new one in
    `to_cohort`. History is retained; over-capacity is a soft warning, never a
    block (Lane F contract)."""
    if to_cohort.is_archived:
        raise ValidationException(_("Target cohort is archived."), code="cohort_archived")

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
