"""Teacher-domain factories (TESTING.md §4). Call inside schema_context(tenant)."""

from __future__ import annotations

import factory

from apps.org.tests.factories import BranchFactory
from apps.teachers.models import TeacherProfile
from apps.users.tests.factories import UserFactory


class TeacherProfileFactory(factory.django.DjangoModelFactory[TeacherProfile]):
    class Meta:
        model = TeacherProfile

    user = factory.SubFactory(UserFactory)
    branch = factory.SubFactory(BranchFactory)
