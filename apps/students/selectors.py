"""Student read selectors with role-based scoping (TD-5)."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.students.models import StudentProfile
from core.permissions import Role

# Roles that see every student in the tenant.
STAFF_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT, Role.TEACHER, Role.REGISTRAR, Role.IT}


def _base_qs() -> QuerySet[StudentProfile]:
    return StudentProfile.objects.select_related("user", "branch", "current_cohort")


def scoped_students(*, user, roles: set[str] | None = None) -> QuerySet[StudentProfile]:
    qs = _base_qs()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if roles & STAFF_ROLES:
        return qs
    if Role.PARENT in roles:  # read_own_children
        return qs.filter(guardians__parent__user=user).distinct()
    if Role.STUDENT in roles:  # read_self
        return qs.filter(user=user)
    return qs.none()  # fail closed


def students_with_upcoming_birthdays(
    *, base: QuerySet[StudentProfile] | None = None, days: int = 7, branch=None, cohort=None
) -> QuerySet[StudentProfile]:
    today = timezone.now().date()
    # Clamp defensively: the (month, day) set is exhaustive at 366 days anyway,
    # so capping is semantically lossless and protects future callers.
    month_days = {
        (today + timedelta(days=offset)).timetuple()[1:3] for offset in range(min(max(days, 0), 366) + 1)
    }
    window = Q()
    for month, day in month_days:
        window |= Q(user__birthdate__month=month, user__birthdate__day=day)
    qs = (base if base is not None else _base_qs()).filter(user__birthdate__isnull=False).filter(window)
    if branch:
        qs = qs.filter(branch_id=branch)
    if cohort:
        qs = qs.filter(current_cohort_id=cohort)
    return qs
