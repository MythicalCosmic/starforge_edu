"""Content read selectors: visibility-scoped library/file queries + the storage
quota meter."""

from __future__ import annotations

from django.db.models import Q, QuerySet, Sum

from apps.content.models import ContentLibrary, LessonFile
from core.permissions import Role

STAFF_ROLES = {Role.DIRECTOR}


def _related_cohort_ids(user) -> set[int]:
    """Cohorts the user belongs to: student member, parent of a member, or a
    teacher of the cohort."""
    from apps.cohorts.models import Cohort

    qs = Cohort.objects.filter(
        Q(memberships__student__user=user, memberships__end_date__isnull=True)
        | Q(
            memberships__student__guardians__parent__user=user,
            memberships__end_date__isnull=True,
        )
        | Q(primary_teacher__user=user)
        | Q(co_teachers__teacher__user=user)
        | Q(lessons__teacher__user=user)
    )
    return set(qs.values_list("id", flat=True))


def _visibility_filter(user, roles: set[str], memberships) -> Q:
    """Q over ContentLibrary matching what `user` may see (TD-13 visibility)."""
    dept_ids = {m.department_id for m in memberships if m.department_id}
    cohort_ids = _related_cohort_ids(user)
    q = Q(visibility=ContentLibrary.Visibility.TENANT)
    q |= Q(visibility=ContentLibrary.Visibility.DEPARTMENT, department_id__in=dept_ids)
    q |= Q(visibility=ContentLibrary.Visibility.COHORT, cohort_id__in=cohort_ids)
    for role in roles:  # role visibility: allowed_roles JSON contains the role
        q |= Q(visibility=ContentLibrary.Visibility.ROLE, allowed_roles__contains=role)
    return q


def scoped_libraries(*, user, roles: set[str] | None = None, memberships=None) -> QuerySet[ContentLibrary]:
    qs = ContentLibrary.objects.filter(is_active=True)
    if user.is_superuser:
        return qs
    if memberships is None:
        memberships = list(user.role_memberships.filter(revoked_at__isnull=True))
    if roles is None:
        roles = {m.role for m in memberships}
    if roles & STAFF_ROLES:
        return qs
    return qs.filter(_visibility_filter(user, roles, memberships)).distinct()


def scoped_files(*, user, roles: set[str] | None = None, memberships=None) -> QuerySet[LessonFile]:
    qs = LessonFile.objects.select_related("lesson", "folder", "uploaded_by")
    if user.is_superuser:
        return qs
    if memberships is None:
        memberships = list(user.role_memberships.filter(revoked_at__isnull=True))
    if roles is None:
        roles = {m.role for m in memberships}
    if roles & STAFF_ROLES:
        return qs
    libs = scoped_libraries(user=user, roles=roles, memberships=memberships)
    return qs.filter(Q(lesson__module__course__library__in=libs) | Q(folder__library__in=libs)).distinct()


def storage_used_bytes() -> int:
    """Total bytes of CLEAN files in the current tenant (D3-E billing meter)."""
    return (
        LessonFile.objects.filter(status=LessonFile.Status.CLEAN).aggregate(total=Sum("size_bytes"))["total"]
        or 0
    )
