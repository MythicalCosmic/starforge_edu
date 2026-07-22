"""ORM-backed parent repository — bakes in select_related and the role scoping."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.parents.interfaces.repositories import IParentRepository
from apps.parents.models import ParentProfile
from apps.parents.repositories.scoping import scope_rows
from core.repositories import BaseRepository


class ParentRepository(BaseRepository[ParentProfile], IParentRepository):
    model = ParentProfile

    def get_queryset(self) -> QuerySet[ParentProfile]:
        return ParentProfile.objects.select_related("user")

    def scoped(self, *, user, roles) -> QuerySet[ParentProfile]:
        return scope_rows(
            self.get_queryset(),
            user=user,
            roles=roles,
            own_filter={"user": user},
            branch_field="guardianships__student__branch_id",
            department_field="guardianships__student__current_cohort__department_id",
        )

    def get_scoped(self, *, user, roles, pk: int) -> ParentProfile | None:
        return self.scoped(user=user, roles=roles).filter(pk=pk).first()

    def profile_for(self, user) -> ParentProfile | None:
        return self.get_queryset().filter(user=user).first()

    def students_for(self, parent, *, user=None, roles=None) -> QuerySet:
        # The sanctioned parents->students link (Guardian). select_related the
        # relations the student presenter reads so a family list is not N+1.
        from apps.students.models import StudentProfile

        qs = (
            StudentProfile.objects.filter(guardians__parent=parent)
            .select_related("user", "branch")
            .distinct()
        )
        if user is None:
            return qs
        return scope_rows(
            qs,
            user=user,
            roles=roles,
            own_filter={"guardians__parent__user": user},
            branch_field="branch_id",
            department_field="current_cohort__department_id",
        )

    def all_students_in_scope(self, parent, *, user, roles) -> bool:
        # The caller wraps parent-wide mutations in one transaction. Locking the
        # parent also makes a concurrent Guardian FK insert wait, so the all-child
        # scope check cannot be invalidated immediately before update/delete.
        if not ParentProfile.objects.select_for_update().filter(pk=parent.pk).exists():
            return False
        all_students = self.students_for(parent)
        scoped_ids = self.students_for(parent, user=user, roles=roles).values("pk")
        return not all_students.exclude(pk__in=scoped_ids).exists()
