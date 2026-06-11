"""Org-domain factories (TESTING.md §4). Call inside schema_context(tenant)."""

from __future__ import annotations

import factory

from apps.org.models import Branch, Department


class BranchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Branch
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Branch {n}")
    slug = factory.Sequence(lambda n: f"branch-{n}")


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department
        django_get_or_create = ("branch", "slug")

    branch = factory.SubFactory(BranchFactory)
    name = factory.Sequence(lambda n: f"Department {n}")
    slug = factory.Sequence(lambda n: f"dept-{n}")
