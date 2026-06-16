"""Schedule read selectors: conflict detection + role-scoped lesson queries."""

from __future__ import annotations

from collections.abc import Iterable

from django.db.models import QuerySet

from apps.schedule.models import Lesson
from core.permissions import Role

STAFF_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT, Role.REGISTRAR, Role.IT, Role.TEACHER}


def check_conflicts(
    *,
    starts_at,
    ends_at,
    cohort_id: int,
    teacher_id: int,
    room_id: int | None = None,
    exclude_lesson_ids: Iterable[int] = (),
) -> dict[str, list[int]]:
    """Conflicting SCHEDULED lesson IDs grouped by dimension. Range overlap is
    half-open: touching edges (end == start) is NOT a conflict."""
    overlapping = Lesson.objects.filter(
        status=Lesson.Status.SCHEDULED, starts_at__lt=ends_at, ends_at__gt=starts_at
    )
    ids = list(exclude_lesson_ids)
    if ids:
        overlapping = overlapping.exclude(id__in=ids)

    conflicts: dict[str, list[int]] = {}
    teacher_hits = list(overlapping.filter(teacher_id=teacher_id).values_list("id", flat=True))
    if teacher_hits:
        conflicts["teacher"] = teacher_hits
    cohort_hits = list(overlapping.filter(cohort_id=cohort_id).values_list("id", flat=True))
    if cohort_hits:
        conflicts["cohort"] = cohort_hits
    if room_id is not None:
        room_hits = list(overlapping.filter(room_id=room_id).values_list("id", flat=True))
        if room_hits:
            conflicts["room"] = room_hits
    return conflicts


def _base_lessons() -> QuerySet[Lesson]:
    return Lesson.objects.select_related("cohort", "teacher__user", "room", "term", "rule")


def scoped_lessons(*, user, roles: set[str] | None = None) -> QuerySet[Lesson]:
    qs = _base_lessons()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if roles & STAFF_ROLES:
        return qs
    if Role.PARENT in roles:  # children's cohort lessons
        return qs.filter(cohort__current_students__guardians__parent__user=user).distinct()
    if Role.STUDENT in roles:  # own cohort lessons
        return qs.filter(cohort__current_students__user=user).distinct()
    return qs.none()
