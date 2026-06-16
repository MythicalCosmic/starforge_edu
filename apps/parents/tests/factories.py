"""Parent-domain factories (TESTING.md §4). Call inside schema_context(tenant)."""

from __future__ import annotations

import factory

from apps.parents.models import Guardian, ParentProfile
from apps.students.tests.factories import StudentProfileFactory
from apps.users.tests.factories import UserFactory


class ParentProfileFactory(factory.django.DjangoModelFactory[ParentProfile]):
    class Meta:
        model = ParentProfile

    user = factory.SubFactory(UserFactory)


class GuardianFactory(factory.django.DjangoModelFactory[Guardian]):
    class Meta:
        model = Guardian

    parent = factory.SubFactory(ParentProfileFactory)
    student = factory.SubFactory(StudentProfileFactory)
    relationship = Guardian.Relationship.MOTHER
