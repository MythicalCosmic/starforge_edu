"""ParentService — parent CRUD + linked-students + parent self-service."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from apps.parents.dto.parent_dto import ParentCreateDTO
from apps.parents.interfaces.repositories import IParentRepository
from apps.parents.interfaces.services import IParentService
from apps.parents.models import ParentProfile
from core.exceptions import NotFoundException

_UPDATABLE = ("workplace", "notes")


class ParentService(IParentService):
    def __init__(self, parents: IParentRepository) -> None:
        self._parents = parents

    def scoped_list(self, *, user, roles) -> QuerySet[ParentProfile]:
        return self._parents.scoped(user=user, roles=roles)

    def get(self, *, user, roles, pk: int) -> ParentProfile | None:
        return self._parents.get_scoped(user=user, roles=roles, pk=pk)

    def create(self, data: ParentCreateDTO) -> ParentProfile:
        from apps.parents.services import create_parent

        return create_parent(
            phone=data.phone,
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            middle_name=data.middle_name,
            birthdate=data.birthdate,
            gender=data.gender,
            workplace=data.workplace,
            notes=data.notes,
        )

    def update(self, parent: ParentProfile, changes: dict[str, Any]) -> ParentProfile:
        for field in _UPDATABLE:
            if field in changes:
                setattr(parent, field, changes[field])
        parent.save()
        return parent

    def delete(self, parent: ParentProfile) -> None:
        self._parents.delete(parent)

    def students(self, parent: ParentProfile) -> QuerySet:
        return self._parents.students_for(parent)

    def require_profile(self, user) -> ParentProfile:
        parent = self._parents.profile_for(user)
        if parent is None:
            raise NotFoundException(_("You do not have a parent profile."), code="not_a_parent")
        return parent

    def child_or_404(self, parent: ParentProfile, student_id: int):
        student = self._parents.students_for(parent).filter(pk=student_id).first()
        if student is None:
            raise NotFoundException(_("That is not one of your children."), code="not_your_child")
        return student
