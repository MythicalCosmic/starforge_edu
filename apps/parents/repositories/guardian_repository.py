"""ORM-backed guardian repository (parent↔student links)."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.parents.interfaces.repositories import IGuardianRepository
from apps.parents.models import Guardian
from apps.parents.repositories.scoping import scope_rows
from core.repositories import BaseRepository


class GuardianRepository(BaseRepository[Guardian], IGuardianRepository):
    model = Guardian

    def get_queryset(self) -> QuerySet[Guardian]:
        return Guardian.objects.select_related("parent__user", "student__user")

    def scoped(self, *, user, roles) -> QuerySet[Guardian]:
        return scope_rows(
            self.get_queryset(),
            user=user,
            roles=roles,
            own_filter={"parent__user": user},
            branch_field="student__branch_id",
            department_field="student__current_cohort__department_id",
        )

    def get_scoped(self, *, user, roles, pk: int) -> Guardian | None:
        return self.scoped(user=user, roles=roles).filter(pk=pk).first()
