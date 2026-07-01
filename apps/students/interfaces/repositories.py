"""Student repository port. Scoping is role-based (staff all / parent children /
student self) — delegated to the preserved apps.students.selectors."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.students.models import StudentProfile
from core.interfaces import IBaseRepository


class IStudentRepository(IBaseRepository[StudentProfile]):
    def scoped(self, *, user, roles) -> QuerySet[StudentProfile]:
        """The students the caller may see (role-based, TD-5)."""
        raise NotImplementedError

    def get_scoped(self, *, user, roles, pk: int) -> StudentProfile | None:
        """A single in-scope student by pk, or None (out-of-role-scope reads 404)."""
        raise NotImplementedError

    def profile_for(self, user) -> StudentProfile | None:
        """The signed-in user's own student profile (self-service), or None."""
        raise NotImplementedError
