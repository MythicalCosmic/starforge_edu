"""Academics read selectors: publication-gated, role-scoped Grade/Transcript
queries + honor-roll / academic-warning lists."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.academics.models import Exam, Grade, Transcript
from apps.org.selectors import get_center_settings
from core.permissions import PermissionRoleSet, Role
from core.scoping import permission_membership_scope_q, role_membership_scope_q

# Director is tenant-wide; HoD follows exact branch/department memberships;
# teacher is limited to taught cohorts; student/parent remain self/children scoped.


def _cohorts_taught_by(user) -> QuerySet:
    from apps.cohorts.selectors import taught_cohorts

    return taught_cohorts(user=user).values_list("id", flat=True)


def _grade_base() -> QuerySet[Grade]:
    return Grade.objects.select_related("student__user", "subject", "term")


def scoped_grades(*, user, roles: set[str] | None = None) -> QuerySet[Grade]:
    qs = _grade_base()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs
    visible = permission_membership_scope_q(
        roles=roles,
        permission="academics:read",
        branch_field="student__branch_id",
        department_field="student__current_cohort__department_id",
        account_kinds={"staff"},
    )
    if not isinstance(roles, PermissionRoleSet) and Role.HEAD_OF_DEPT in roles:
        visible |= role_membership_scope_q(
            user=user,
            roles={Role.HEAD_OF_DEPT},
            branch_field="student__branch_id",
            department_field="student__current_cohort__department_id",
        )
    if Role.TEACHER in roles:  # natural ownership: cohorts this teacher actually teaches
        visible |= Q(
            student__cohort_memberships__end_date__isnull=True,
            student__cohort_memberships__cohort_id__in=_cohorts_taught_by(user),
        )
    if Role.PARENT in roles:  # published only, guardian-linked children
        visible |= Q(is_published=True, student__guardians__parent__user=user)
    if Role.STUDENT in roles:  # published only, self
        visible |= Q(is_published=True, student__user=user)
    return qs.filter(visible).distinct()


def scoped_transcripts(*, user, roles: set[str] | None = None) -> QuerySet[Transcript]:
    qs = Transcript.objects.select_related("student__user", "term")
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs
    visible = permission_membership_scope_q(
        roles=roles,
        permission="academics:read",
        branch_field="student__branch_id",
        department_field="student__current_cohort__department_id",
        account_kinds={"staff"},
    )
    if not isinstance(roles, PermissionRoleSet) and Role.HEAD_OF_DEPT in roles:
        visible |= role_membership_scope_q(
            user=user,
            roles={Role.HEAD_OF_DEPT},
            branch_field="student__branch_id",
            department_field="student__current_cohort__department_id",
        )
    if Role.PARENT in roles:
        visible |= Q(student__guardians__parent__user=user)
    if Role.STUDENT in roles:
        visible |= Q(student__user=user)
    return qs.filter(visible).distinct()


def scoped_exams(*, user, roles: set[str] | None = None) -> QuerySet[Exam]:
    """Exams visible/mutable for `user`. Director is tenant-wide and HoD membership-scoped;
    a TEACHER is limited to exams of cohorts they teach (so the results /
    import-csv / publish write actions 404 on out-of-cohort exams via
    get_object()); everyone else sees none."""
    qs = Exam.objects.select_related("subject", "cohort", "term", "exam_type")
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs
    visible = permission_membership_scope_q(
        roles=roles,
        permission="academics:read",
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
    if Role.TEACHER in roles:
        visible |= Q(cohort_id__in=_cohorts_taught_by(user))
    return qs.filter(visible).distinct()


def _report_scope(qs: QuerySet[Grade], *, user, roles: set[str] | None) -> QuerySet[Grade]:
    """Scope a report queryset for consistency with grade scoping: director is
    tenant-wide, HoD membership-scoped, and a TEACHER is limited to
    grades of students in cohorts they teach. `user=None` keeps tenant-wide
    behaviour (e.g. direct selector calls in tests / internal aggregates)."""
    if user is None or getattr(user, "is_superuser", False):
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs
    visible = permission_membership_scope_q(
        roles=roles,
        permission="academics:read",
        branch_field="student__branch_id",
        department_field="student__current_cohort__department_id",
        account_kinds={"staff"},
    )
    if not isinstance(roles, PermissionRoleSet) and Role.HEAD_OF_DEPT in roles:
        visible |= role_membership_scope_q(
            user=user,
            roles={Role.HEAD_OF_DEPT},
            branch_field="student__branch_id",
            department_field="student__current_cohort__department_id",
        )
    if Role.TEACHER in roles:
        visible |= Q(
            student__cohort_memberships__end_date__isnull=True,
            student__cohort_memberships__cohort_id__in=_cohorts_taught_by(user),
        )
    return qs.filter(visible).distinct()


def honor_roll(*, term_id: int, settings=None, user=None, roles: set[str] | None = None) -> QuerySet[Grade]:
    """Published grades for the term at or above `honor_roll_min` (TD-13).
    Teacher-scoped to taught cohorts; director tenant-wide; HoD membership-scoped."""
    settings = settings or get_center_settings()
    qs = (
        _grade_base()
        .filter(term_id=term_id, is_published=True, value_raw__gte=settings.honor_roll_min)
        .order_by("-value_raw")
    )
    return _report_scope(qs, user=user, roles=roles)


def academic_warnings(
    *, term_id: int, settings=None, user=None, roles: set[str] | None = None
) -> QuerySet[Grade]:
    """Published grades for the term at or below `academic_warning_max` (TD-13).
    Teacher-scoped to taught cohorts; director tenant-wide; HoD membership-scoped."""
    settings = settings or get_center_settings()
    qs = (
        _grade_base()
        .filter(term_id=term_id, is_published=True, value_raw__lte=settings.academic_warning_max)
        .order_by("value_raw")
    )
    return _report_scope(qs, user=user, roles=roles)
