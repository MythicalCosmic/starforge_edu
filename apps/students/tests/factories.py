"""Student-domain factories (TESTING.md §4). Call inside schema_context(tenant).

Creates rows directly for test fixtures; the enrollment state machine and
generated IDs are exercised via the service in the API tests."""

from __future__ import annotations

import factory

from apps.org.tests.factories import BranchFactory
from apps.students.models import StudentProfile
from apps.users.tests.factories import UserFactory


class StudentProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StudentProfile

    user = factory.SubFactory(UserFactory)
    branch = factory.SubFactory(BranchFactory)
    student_id = factory.Sequence(lambda n: f"STU-{n:05d}")
    status = StudentProfile.Status.ACTIVE
