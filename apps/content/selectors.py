"""Content read selectors: visibility-scoped library/file queries + the storage
quota meter."""

from __future__ import annotations

from django.db.models import Q, QuerySet, Sum

from apps.content.models import ContentLibrary, LessonFile
from core.permissions import PermissionRoleSet, Role, has_permission_code
from core.scoping import permission_membership_scope_q

# F4-5 content review/publication. REVIEWER_ROLES are the content staff (vs
# learners): they may see files still pending dual approval and may download a
# view-only file. Reach differs by role: a DIRECTOR sees every file tenant-wide;
# a HEAD_OF_DEPT (manager) stays department-scoped like everywhere else but
# additionally reaches any file still pending the manager sign-off so they can
# counter-sign content anywhere — they get NO blanket read of already-published
# content in libraries outside their scope. A TEACHER/LIBRARIAN sees drafts only
# within their own library visibility. Everyone else (students, parents,
# non-academic staff) sees only dual-approved, published files.
REVIEWER_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT, Role.TEACHER, Role.LIBRARIAN}
_MANAGER_APPROVAL_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT}
_CONTENT_SCOPE_PERMISSIONS = (
    "content:read",
    "content:write",
    "content:approve",
    "content:publish",
)


def has_global_content_scope(roles: set[str]) -> bool:
    """Whether the caller holds the protected owner wildcard."""
    if isinstance(roles, PermissionRoleSet):
        return has_permission_code(roles, "*:*")
    return Role.DIRECTOR in roles


def can_review_content(roles: set[str]) -> bool:
    """Whether drafts should be visible for an approval workflow."""
    if isinstance(roles, PermissionRoleSet):
        return has_permission_code(roles, "content:approve") or has_permission_code(roles, "content:publish")
    return bool(roles & REVIEWER_ROLES)


def can_publish_content(roles: set[str]) -> bool:
    """Whether the caller may provide the elevated second sign-off.

    The manager leg requires an explicit ``content:publish`` grant (or the owner
    wildcard). A broad ``content:*`` authoring grant still permits the first
    review, but does not silently turn a teacher or librarian into the second
    maker-checker signer.
    """
    if not isinstance(roles, PermissionRoleSet):
        return bool(roles & _MANAGER_APPROVAL_ROLES)
    for membership in roles.membership_scopes:
        if membership.is_legacy_fallback:
            if membership.role in _MANAGER_APPROVAL_ROLES:
                return True
            continue
        if "*:*" in membership.grants or "content:publish" in membership.grants:
            return True
    return False


def _related_cohort_ids(user) -> set[int]:
    """Cohorts the user belongs to: student member, parent of a member, or a
    teacher of the cohort."""
    from apps.cohorts.models import Cohort
    from apps.cohorts.selectors import taught_cohorts

    qs = Cohort.objects.filter(
        Q(memberships__student__user=user, memberships__end_date__isnull=True)
        | Q(
            memberships__student__guardians__parent__user=user,
            memberships__end_date__isnull=True,
        )
        | Q(pk__in=taught_cohorts(user=user).values("pk"))
    )
    return set(qs.values_list("id", flat=True))


def _visibility_filter(user, roles: set[str], memberships) -> Q:
    """Q over ContentLibrary matching what `user` may see (TD-13 visibility)."""
    dept_ids = {m.department_id for m in memberships if m.department_id}
    cohort_ids = _related_cohort_ids(user)
    q = Q(visibility=ContentLibrary.Visibility.TENANT)
    if isinstance(roles, PermissionRoleSet):
        # The selector backs read, write, and approval endpoints. Their permission
        # gates choose the operation; this union binds that operation to the exact
        # membership that supplies it, so a Branch A grant cannot borrow Branch B.
        department_scope = Q(pk__in=[])
        cohort_scope = Q(pk__in=[])
        for permission in _CONTENT_SCOPE_PERMISSIONS:
            department_scope |= permission_membership_scope_q(
                roles=roles,
                permission=permission,
                branch_field="department__branch_id",
                department_field="department_id",
                account_kinds={"staff", "teacher"},
            )
            cohort_scope |= permission_membership_scope_q(
                roles=roles,
                permission=permission,
                branch_field="cohort__branch_id",
                department_field="cohort__department_id",
                account_kinds={"staff", "teacher"},
            )
        q |= Q(visibility=ContentLibrary.Visibility.DEPARTMENT) & department_scope
        q |= Q(visibility=ContentLibrary.Visibility.COHORT) & cohort_scope
    else:
        # Direct selector calls/tests may pass a plain role set (legacy contract).
        q |= Q(visibility=ContentLibrary.Visibility.DEPARTMENT, department_id__in=dept_ids)
    q |= Q(visibility=ContentLibrary.Visibility.COHORT, cohort_id__in=cohort_ids)
    # A canonical custom STAFF type must not inherit its compatibility SUPPORT
    # scope. Teacher/student/parent are natural identity relationships and retain
    # their legacy role-library visibility during this transition.
    visible_roles = roles
    if isinstance(roles, PermissionRoleSet):
        natural_role_by_kind = {
            "teacher": Role.TEACHER,
            "student": Role.STUDENT,
            "parent": Role.PARENT,
        }
        visible_roles = {
            natural_role_by_kind[kind] for kind in roles.account_kinds if kind in natural_role_by_kind
        }
    for role in visible_roles:  # role visibility: allowed_roles JSON contains the role
        q |= Q(visibility=ContentLibrary.Visibility.ROLE, allowed_roles__contains=role)
    return q


def scoped_libraries(*, user, roles: set[str] | None = None, memberships=None) -> QuerySet[ContentLibrary]:
    # select_related the labelled FKs the presenter dereferences (department/cohort
    # names) — no N+1 on the list, and harmless when this qs is used as an `__in=`
    # subquery elsewhere (Django selects only the pk there).
    # Managers must retain a path to an inactive library so it can be audited or
    # reactivated through the API.  Ordinary readers still see active libraries
    # only; applying the active filter before the manager bypass made deactivation
    # an irreversible API operation.
    qs = ContentLibrary.objects.select_related("department", "cohort")
    if user.is_superuser:
        return qs
    if memberships is None:
        memberships = list(user.role_memberships.filter(revoked_at__isnull=True))
    if roles is None:
        roles = {m.role for m in memberships}
    if has_global_content_scope(roles):
        return qs
    return qs.filter(is_active=True).filter(_visibility_filter(user, roles, memberships)).distinct()


def scoped_files(*, user, roles: set[str] | None = None, memberships=None) -> QuerySet[LessonFile]:
    qs = LessonFile.objects.select_related("lesson", "folder", "uploaded_by")
    if user.is_superuser:
        return qs
    if memberships is None:
        memberships = list(user.role_memberships.filter(revoked_at__isnull=True))
    if roles is None:
        roles = {m.role for m in memberships}
    if has_global_content_scope(roles):
        return qs  # protected owner: every file tenant-wide
    libs = scoped_libraries(user=user, roles=roles, memberships=memberships)
    visible = Q(lesson__module__course__library__in=libs) | Q(folder__library__in=libs)
    if not isinstance(roles, PermissionRoleSet) and Role.HEAD_OF_DEPT in roles:
        # Manager: own visibility scope PLUS any file still pending the manager
        # sign-off (so they can counter-sign content anywhere) — least privilege,
        # no blanket read of published content outside their scope (F4-5 review).
        return qs.filter(visible | Q(is_approved_manager=False)).distinct()
    if can_review_content(roles):
        # Canonical reviewer/publisher grants and legacy teacher/librarian roles
        # see drafts only within their exact library scope.
        return qs.filter(visible).distinct()
    # Learners (and any non-reviewer): only dual-approved, published files.
    return qs.filter(visible, is_approved_teacher=True, is_approved_manager=True).distinct()


def storage_used_bytes() -> int:
    """Total bytes of CLEAN files in the current tenant (D3-E billing meter)."""
    return (
        LessonFile.objects.filter(status=LessonFile.Status.CLEAN).aggregate(total=Sum("size_bytes"))["total"]
        or 0
    )
