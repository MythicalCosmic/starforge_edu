"""Cohort read selectors."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.cohorts.models import Cohort, CohortMembership


def list_cohorts() -> QuerySet[Cohort]:
    return Cohort.objects.select_related(
        "branch", "department", "primary_teacher__user", "default_room"
    ).prefetch_related("co_teachers__teacher__user")


def cohort_members(*, cohort: Cohort) -> QuerySet[CohortMembership]:
    return (
        CohortMembership.objects.filter(cohort=cohort, end_date__isnull=True)
        .select_related("student__user")
        .order_by("student__user__last_name")
    )
