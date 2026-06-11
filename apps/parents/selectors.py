"""Parent read selectors with role scoping (TD-5)."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.parents.models import Guardian, ParentProfile
from core.permissions import Role

STAFF_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT, Role.REGISTRAR, Role.IT}


def scoped_parents(*, user, roles: set[str] | None = None) -> QuerySet[ParentProfile]:
    qs = ParentProfile.objects.select_related("user")
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if roles & STAFF_ROLES:
        return qs
    if Role.PARENT in roles:
        return qs.filter(user=user)
    return qs.none()


def scoped_guardians(*, user, roles: set[str] | None = None) -> QuerySet[Guardian]:
    qs = Guardian.objects.select_related("parent__user", "student__user")
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if roles & STAFF_ROLES:
        return qs
    if Role.PARENT in roles:
        return qs.filter(parent__user=user)
    return qs.none()


def students_for_parent(*, parent: ParentProfile):
    from apps.students.models import StudentProfile

    return StudentProfile.objects.filter(guardians__parent=parent).select_related("user", "branch").distinct()
