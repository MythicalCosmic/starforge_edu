"""GuardianService — parent↔student links (create + delete; no update by design)."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _

from apps.parents.dto.parent_dto import GuardianCreateDTO
from apps.parents.interfaces.repositories import IGuardianRepository
from apps.parents.interfaces.services import IGuardianService
from apps.parents.models import Guardian
from apps.parents.repositories.scoping import SCOPED_STAFF_ROLES, scope_rows
from core.exceptions import ValidationException
from core.permissions import Role


class GuardianService(IGuardianService):
    def __init__(self, guardians: IGuardianRepository) -> None:
        self._guardians = guardians

    def scoped_list(self, *, user, roles) -> QuerySet[Guardian]:
        return self._guardians.scoped(user=user, roles=roles)

    def get(self, *, user, roles, pk: int) -> Guardian | None:
        return self._guardians.get_scoped(user=user, roles=roles, pk=pk)

    def create(self, data: GuardianCreateDTO, *, user, roles) -> Guardian:
        from apps.parents.services import link_guardian

        return link_guardian(
            parent=self._resolve_parent(data.parent_id, user=user, roles=roles),
            student=self._resolve_student(data.student_id, user=user, roles=roles),
            relationship=self._validate_relationship(data.relationship),
            is_primary=data.is_primary,
            custody_notes=data.custody_notes,
        )

    def delete(self, guardian: Guardian) -> None:
        self._guardians.delete(guardian)

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _validate_relationship(value: str) -> str:
        if value not in Guardian.Relationship.values:
            raise ValidationException(
                _("Invalid relationship."),
                code="validation_error",
                fields={"relationship": ["Not a valid choice."]},
            )
        return value

    @staticmethod
    def _resolve_parent(parent_id: int, *, user, roles):
        from apps.parents.models import ParentProfile

        role_set = set(roles or ())
        base = ParentProfile.objects.all()
        scoped = scope_rows(
            base,
            user=user,
            roles=role_set,
            own_filter={"user": user},
            branch_field="guardianships__student__branch_id",
            department_field="guardianships__student__current_cohort__department_id",
        )
        # A newly-created parent has no branch-bearing guardian link yet. Scoped
        # staff may attach that unassigned record to an in-scope student, but may
        # not reuse a parent already belonging solely to another scope.
        if (
            not getattr(user, "is_superuser", False)
            and Role.DIRECTOR not in role_set
            and role_set & SCOPED_STAFF_ROLES
        ):
            scoped = base.filter(Q(pk__in=scoped.values("pk")) | Q(guardianships__isnull=True)).distinct()
        parent = scoped.filter(pk=parent_id).first()
        if parent is None:
            raise ValidationException(
                _("Invalid parent."), code="invalid_parent", fields={"parent": ["Not found."]}
            )
        return parent

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
