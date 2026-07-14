"""Schedule read selectors: conflict detection + role-scoped lesson queries."""

from __future__ import annotations

from collections.abc import Iterable

from django.db.models import Q, QuerySet

from apps.schedule.models import Lesson, RecurrenceRule
from core.permissions import PermissionRoleSet, Role
from core.scoping import (
    permission_membership_scope_q,
    permission_membership_scopes,
    role_membership_scope_q,
)

SCOPED_STAFF_ROLES = {Role.HEAD_OF_DEPT, Role.REGISTRAR, Role.IT}


def _kind_can_read_schedule(roles: set[str], kind: str, legacy_role: str) -> bool:
    if isinstance(roles, PermissionRoleSet):
        return bool(
            permission_membership_scopes(
                roles=roles,
                permission="schedule:read",
                account_kinds={kind},
            )
        )
    return legacy_role in roles


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


def check_occurrence_conflicts(
    occurrences: Iterable[tuple],
    *,
    cohort_id: int,
    teacher_id: int,
    room_id: int | None = None,
    exclude_lesson_ids: Iterable[int] = (),
) -> dict[str, list[int]]:
    """Check a whole recurrence expansion with one bounded lesson query.

    The old materializer issued up to three overlap queries per occurrence, turning
    a normal daily term into more than a thousand round trips. We load only lessons
    that overlap the expansion's outer window and compare the small candidate set in
    memory; PostgreSQL exclusion constraints remain the race-condition backstop.
    """
    occurrence_list = list(occurrences)
    if not occurrence_list:
        return {}
    window_start = min(start for start, _end in occurrence_list)
    window_end = max(end for _start, end in occurrence_list)
    resource_filter = Q(cohort_id=cohort_id) | Q(teacher_id=teacher_id)
    if room_id is not None:
        resource_filter |= Q(room_id=room_id)
    candidates = Lesson.objects.filter(
        resource_filter,
        status=Lesson.Status.SCHEDULED,
        starts_at__lt=window_end,
        ends_at__gt=window_start,
    )
    excluded = list(exclude_lesson_ids)
    if excluded:
        candidates = candidates.exclude(id__in=excluded)

    hits: dict[str, set[int]] = {"teacher": set(), "cohort": set(), "room": set()}
    for lesson in candidates.only("id", "starts_at", "ends_at", "teacher_id", "cohort_id", "room_id"):
        if not any(start < lesson.ends_at and end > lesson.starts_at for start, end in occurrence_list):
            continue
        if lesson.teacher_id == teacher_id:
            hits["teacher"].add(lesson.id)
        if lesson.cohort_id == cohort_id:
            hits["cohort"].add(lesson.id)
        if room_id is not None and lesson.room_id == room_id:
            hits["room"].add(lesson.id)
    return {dimension: sorted(ids) for dimension, ids in hits.items() if ids}


def _base_lessons() -> QuerySet[Lesson]:
    return Lesson.objects.select_related("cohort", "teacher__user", "room", "term", "rule", "lesson_type")


def _base_rules() -> QuerySet[RecurrenceRule]:
    return RecurrenceRule.objects.select_related("term", "cohort", "teacher__user", "room", "lesson_type")


def scoped_rules(*, user, roles: set[str] | None = None) -> QuerySet[RecurrenceRule]:
    """Rules visible through the schedule read surface.

    This deliberately mirrors :func:`scoped_lessons`: recurrence metadata must
    not provide a tenant-wide bypass around the cohort-scoped lesson feed.
    """
    qs = _base_rules()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs

    visible = Q(pk__in=[])
    scoped_staff = roles & SCOPED_STAFF_ROLES
    if scoped_staff and not isinstance(roles, PermissionRoleSet):
        visible |= role_membership_scope_q(
            user=user,
            roles=scoped_staff,
            branch_field="cohort__branch_id",
            department_field="cohort__department_id",
        )
    visible |= permission_membership_scope_q(
        roles=roles,
        permission="schedule:read",
        branch_field="cohort__branch_id",
        department_field="cohort__department_id",
        account_kinds={"staff"},
    )
    if _kind_can_read_schedule(roles, "teacher", Role.TEACHER):
        visible |= (
            Q(teacher__user=user)
            | Q(cohort__co_teachers__teacher__user=user)
            | Q(cohort__primary_teacher__user=user)
        )
    if _kind_can_read_schedule(roles, "parent", Role.PARENT):
        visible |= Q(
            cohort__memberships__student__guardians__parent__user=user,
            cohort__memberships__end_date__isnull=True,
        )
    if _kind_can_read_schedule(roles, "student", Role.STUDENT):
        visible |= Q(
            cohort__memberships__student__user=user,
            cohort__memberships__end_date__isnull=True,
        )
    return qs.filter(visible).distinct()


def scoped_lessons(*, user, roles: set[str] | None = None) -> QuerySet[Lesson]:
    qs = _base_lessons()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs

    visible = Q(pk__in=[])
    scoped_staff = roles & SCOPED_STAFF_ROLES
    if scoped_staff and not isinstance(roles, PermissionRoleSet):
        visible |= role_membership_scope_q(
            user=user,
            roles=scoped_staff,
            branch_field="cohort__branch_id",
            department_field="cohort__department_id",
        )
    visible |= permission_membership_scope_q(
        roles=roles,
        permission="schedule:read",
        branch_field="cohort__branch_id",
        department_field="cohort__department_id",
        account_kinds={"staff"},
    )
    if _kind_can_read_schedule(roles, "teacher", Role.TEACHER):  # D2-A-6: own taught lessons only
        visible |= (
            Q(teacher__user=user)
            | Q(cohort__co_teachers__teacher__user=user)
            | Q(cohort__primary_teacher__user=user)
        )
    if _kind_can_read_schedule(roles, "parent", Role.PARENT):  # children's active-cohort lessons
        visible |= Q(
            cohort__memberships__student__guardians__parent__user=user,
            cohort__memberships__end_date__isnull=True,
        )
    if _kind_can_read_schedule(roles, "student", Role.STUDENT):  # own active-cohort lessons
        visible |= Q(
            cohort__memberships__student__user=user,
            cohort__memberships__end_date__isnull=True,
        )
    return qs.filter(visible).distinct()
