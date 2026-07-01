"""ORM-backed cohort repository.

The list presenter renders only FK ids (branch/department/primary_teacher/
default_room) plus the nested ``co_teachers``, so the only relation traversed per
row is ``co_teachers`` — prefetch it so a page of N cohorts stays 2 queries, not
1 + N.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.cohorts.interfaces.repositories import ICohortRepository
from apps.cohorts.models import Cohort, CohortMembership
from core.repositories import BaseRepository


class CohortRepository(BaseRepository[Cohort], ICohortRepository):
    model = Cohort

    def get_queryset(self) -> QuerySet[Cohort]:
        return Cohort.objects.prefetch_related("co_teachers")

    def has_memberships(self, cohort: Cohort) -> bool:
        return cohort.memberships.exists()

    def active_members(self, cohort: Cohort) -> QuerySet[CohortMembership]:
        return (
            CohortMembership.objects.filter(cohort=cohort, end_date__isnull=True)
            .select_related("student__user")
            .order_by("student__user__last_name")
        )
