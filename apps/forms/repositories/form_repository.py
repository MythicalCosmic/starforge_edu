"""ORM-backed forms repository (role-scoped reads)."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.forms.interfaces.repositories import IFormRepository
from apps.forms.models import Form
from core.repositories import BaseRepository


class FormRepository(BaseRepository[Form], IFormRepository):
    model = Form

    def get_queryset(self) -> QuerySet[Form]:
        return Form.objects.select_related("branch", "created_by").prefetch_related("fields")

    def scoped(
        self,
        *,
        user,
        is_unscoped: bool,
        can_write: bool,
        read_branch_ids: set[int],
        write_branch_ids: set[int],
    ) -> QuerySet[Form]:
        qs = self.get_queryset()
        if is_unscoped:
            return qs  # the director sees the whole centre
        if can_write:
            # A builder can also discover published centre-wide forms so they may
            # answer them. Lifecycle/response management applies the narrower
            # creator-or-branch gate in the view after this visibility query.
            return qs.filter(
                Q(created_by=user)
                | Q(branch_id__in=write_branch_ids)
                | (
                    Q(status=Form.Status.PUBLISHED)
                    & (Q(branch_id__in=read_branch_ids) | Q(branch__isnull=True))
                )
            )
        # Responders: PUBLISHED forms in their branch, plus centre-wide (branch null).
        return qs.filter(status=Form.Status.PUBLISHED).filter(
            Q(branch_id__in=read_branch_ids) | Q(branch__isnull=True)
        )

    def get_scoped(
        self,
        *,
        user,
        is_unscoped: bool,
        can_write: bool,
        read_branch_ids: set[int],
        write_branch_ids: set[int],
        pk: int,
    ) -> Form | None:
        return (
            self.scoped(
                user=user,
                is_unscoped=is_unscoped,
                can_write=can_write,
                read_branch_ids=read_branch_ids,
                write_branch_ids=write_branch_ids,
            )
            .filter(pk=pk)
            .first()
        )
