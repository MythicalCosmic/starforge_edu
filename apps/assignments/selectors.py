"""Assignments read selectors: role-scoped Assignment/Submission queries.

Drafts and other cohorts' assignments are filtered OUT of a student's queryset
(so they 404 on access, never a 403 that leaks existence)."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.assignments.models import Assignment, Submission
from core.permissions import PermissionRoleSet, Role
from core.scoping import permission_membership_scope_q, role_membership_scope_q

STAFF_ROLES = {Role.DIRECTOR}


def _cohorts_taught_by(user) -> QuerySet:
    from apps.cohorts.selectors import taught_cohorts

    return taught_cohorts(user=user).values_list("id", flat=True)


def scoped_assignments(*, user, roles: set[str] | None = None) -> QuerySet[Assignment]:
    qs = Assignment.objects.select_related("cohort")
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if roles & STAFF_ROLES:
        return qs
    visible = permission_membership_scope_q(
        roles=roles,
        permission="assignments:read",
        branch_field="cohort__branch_id",
        department_field="cohort__department_id",
        account_kinds={"staff"},
    )
    if not isinstance(roles, PermissionRoleSet) and Role.HEAD_OF_DEPT in roles:
        visible |= role_membership_scope_q(
            user=user,
            roles={Role.HEAD_OF_DEPT},
            branch_field="cohort__branch_id",
            department_field="cohort__department_id",
        )
    if Role.TEACHER in roles:  # natural ownership: cohorts this teacher actually teaches
        visible |= Q(cohort_id__in=_cohorts_taught_by(user))
    if Role.STUDENT in roles:  # published only, own cohorts
        visible |= Q(
            status=Assignment.Status.PUBLISHED,
            cohort__memberships__student__user=user,
            cohort__memberships__end_date__isnull=True,
        )
    return qs.filter(visible).distinct()


def scoped_submissions(*, user, roles: set[str] | None = None) -> QuerySet[Submission]:
    qs = Submission.objects.select_related("student__user", "assignment", "grade")
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if roles & STAFF_ROLES:
        return qs
    visible = permission_membership_scope_q(
        roles=roles,
        permission="assignments:read",
        branch_field="assignment__cohort__branch_id",
        department_field="assignment__cohort__department_id",
        account_kinds={"staff"},
    )
    if not isinstance(roles, PermissionRoleSet) and Role.HEAD_OF_DEPT in roles:
        visible |= role_membership_scope_q(
            user=user,
            roles={Role.HEAD_OF_DEPT},
            branch_field="assignment__cohort__branch_id",
            department_field="assignment__cohort__department_id",
        )
    if Role.TEACHER in roles:  # natural ownership: submissions for taught cohorts
        visible |= Q(assignment__cohort_id__in=_cohorts_taught_by(user))
    if Role.STUDENT in roles:  # own submissions only
        visible |= Q(student__user=user)
    return qs.filter(visible).distinct()
