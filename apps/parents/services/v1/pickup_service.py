"""PickupService — pickup-authorization CRUD."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from apps.parents.dto.parent_dto import PickupCreateDTO
from apps.parents.interfaces.repositories import IPickupRepository
from apps.parents.interfaces.services import IPickupService
from apps.parents.models import PickupAuthorization
from apps.parents.repositories.scoping import scope_rows
from core.exceptions import ValidationException

_SCALARS = ("full_name", "phone", "relationship", "is_active")


class PickupService(IPickupService):
    def __init__(self, pickups: IPickupRepository) -> None:
        self._pickups = pickups

    def scoped_list(self, *, user, roles) -> QuerySet[PickupAuthorization]:
        return self._pickups.scoped(user=user, roles=roles)

    def get(self, *, user, roles, pk: int) -> PickupAuthorization | None:
        return self._pickups.get_scoped(user=user, roles=roles, pk=pk)

    def create(self, data: PickupCreateDTO, *, user, roles) -> PickupAuthorization:
        return PickupAuthorization.objects.create(
            student=self._resolve_student(data.student_id, user=user, roles=roles),
            full_name=data.full_name,
            phone=data.phone,
            relationship=data.relationship,
            is_active=data.is_active,
        )

    def update(
        self,
        pickup: PickupAuthorization,
        changes: dict[str, Any],
        *,
        user,
        roles,
    ) -> PickupAuthorization:
        if "student" in changes:
            pickup.student = self._resolve_student(changes["student"], user=user, roles=roles)
        for field in _SCALARS:
            if field in changes:
                setattr(pickup, field, changes[field])
        pickup.save()
        return pickup

    def delete(self, pickup: PickupAuthorization) -> None:
        self._pickups.delete(pickup)

    @staticmethod
    def _resolve_student(student_id: int, *, user, roles):
        from apps.students.models import StudentProfile

        student = (
            scope_rows(
                StudentProfile.objects.all(),
                user=user,
                roles=roles,
                own_filter={"guardians__parent__user": user},
                branch_field="branch_id",
                department_field="current_cohort__department_id",
            )
            .filter(pk=student_id)
            .first()
        )
        if student is None:
            raise ValidationException(
                _("Invalid student."), code="invalid_student", fields={"student": ["Not found."]}
            )
        return student
