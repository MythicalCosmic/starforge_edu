"""ORM-backed achievement repository (role-scoped reads)."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.achievements.interfaces.repositories import IAchievementRepository
from apps.achievements.models import Achievement
from core.repositories import BaseRepository


class AchievementRepository(BaseRepository[Achievement], IAchievementRepository):
    model = Achievement

    def get_queryset(self) -> QuerySet[Achievement]:
        return Achievement.objects.select_related("cohort", "branch", "created_by")

    def scoped(
        self, *, user, is_unscoped: bool, can_write: bool, can_approve: bool, branch_ids: set[int]
    ) -> QuerySet[Achievement]:
        qs = self.get_queryset()
        if is_unscoped:
            return qs  # the director manages the whole centre
        if can_write:
            # Staff manage their own branch's achievements + the active centre-wide
            # globals, plus anything they created (so a teacher sees their own pending
            # request). An approver (HOD/reception) also sees the pending-global queue
            # so they can action the teacher->manager approval flow.
            visible = (
                Q(created_by=user)
                | Q(branch_id__in=branch_ids)
                | (Q(branch__isnull=True) & Q(status=Achievement.Status.ACTIVE))
            )
            if can_approve:
                visible |= Q(branch__isnull=True) & Q(status=Achievement.Status.PENDING)
            return qs.filter(visible)
        return qs.filter(status=Achievement.Status.ACTIVE)  # students/parents: the live catalogue

    def get_scoped(
        self, *, user, is_unscoped: bool, can_write: bool, can_approve: bool, branch_ids: set[int], pk: int
    ) -> Achievement | None:
        return (
            self.scoped(
                user=user,
                is_unscoped=is_unscoped,
                can_write=can_write,
                can_approve=can_approve,
                branch_ids=branch_ids,
            )
            .filter(pk=pk)
            .first()
        )
