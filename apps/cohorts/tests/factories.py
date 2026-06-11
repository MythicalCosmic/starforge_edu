"""Cohort-domain factories (TESTING.md §4). Call inside schema_context(tenant)."""

from __future__ import annotations

from datetime import date

import factory

from apps.cohorts.models import Cohort
from apps.org.tests.factories import BranchFactory


class CohortFactory(factory.django.DjangoModelFactory[Cohort]):
    class Meta:
        model = Cohort
        django_get_or_create = ("branch", "name")

    name = factory.Sequence(lambda n: f"Cohort {n}")
    branch = factory.SubFactory(BranchFactory)
    start_date = date(2026, 1, 1)
    end_date = date(2026, 12, 31)
