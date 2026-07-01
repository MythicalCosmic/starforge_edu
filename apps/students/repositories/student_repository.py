"""ORM-backed student repository — delegates scoping to the (preserved) selectors."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.students.interfaces.repositories import IStudentRepository
from apps.students.models import StudentProfile
from core.repositories import BaseRepository


class StudentRepository(BaseRepository[StudentProfile], IStudentRepository):
    model = StudentProfile

    def get_queryset(self) -> QuerySet[StudentProfile]:
        return StudentProfile.objects.select_related("user", "branch", "current_cohort")

    def scoped(self, *, user, roles) -> QuerySet[StudentProfile]:
        from apps.students.selectors import scoped_students  # role-based, select_related baked in

        return scoped_students(user=user, roles=roles)

    def get_scoped(self, *, user, roles, pk: int) -> StudentProfile | None:
        return self.scoped(user=user, roles=roles).filter(pk=pk).first()

    def profile_for(self, user) -> StudentProfile | None:
        from apps.students.selectors import student_profile_for

        return student_profile_for(user)
