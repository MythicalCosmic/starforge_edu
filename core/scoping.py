"""Branch/department object scoping for the layered (plain-view) style.

A superuser or DIRECTOR sees everything; otherwise a list is filtered to the caller's
role-membership branches and a single object outside them is a 403. Use this in the
repository/service list query and at the detail/write boundary so a branch-scoped role
cannot read or mutate another branch."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db.models import Q, QuerySet

from core.permissions import Role, get_role_memberships


def is_unscoped(request: Any) -> bool:
    """True when the caller bypasses branch scoping (superuser or DIRECTOR)."""
    if getattr(getattr(request, "user", None), "is_superuser", False):
        return True
    return any(m.role == Role.DIRECTOR for m in get_role_memberships(request))


def branch_ids(request: Any) -> set[int]:
    return {m.branch_id for m in get_role_memberships(request) if m.branch_id}


def department_ids(request: Any) -> set[int]:
    return {m.department_id for m in get_role_memberships(request) if m.department_id}


def role_membership_scope_q(
    *,
    user: Any,
    roles: Iterable[str],
    branch_field: str,
    department_field: str | None = None,
) -> Q:
    """Build a fail-closed row-scope for active role memberships.

    A membership without a department grants its whole branch. A membership with
    a department grants only rows in that exact branch/department pair when the
    target model exposes a department path. For branch-only resources, the most
    precise enforceable boundary remains the membership's branch.

    ``roles`` is deliberately explicit: callers can union this predicate with
    another role's natural scope (for example, a user who is both a department HoD
    and a teacher still sees lessons they personally teach).
    """
    role_set = set(roles)
    if not role_set or not getattr(user, "is_authenticated", False):
        return Q(pk__in=[])

    memberships = list(
        user.role_memberships.filter(
            revoked_at__isnull=True,
            role__in=role_set,
        ).values_list("branch_id", "department_id")
    )
    if not memberships:
        return Q(pk__in=[])

    branch_wide = {branch_id for branch_id, department_id in memberships if department_id is None}
    scoped = Q(**{f"{branch_field}__in": branch_wide}) if branch_wide else Q(pk__in=[])
    for branch_id, department_id in memberships:
        if department_id is None:
            continue
        if department_field is None:
            scoped |= Q(**{branch_field: branch_id})
        else:
            scoped |= Q(
                **{
                    branch_field: branch_id,
                    department_field: department_id,
                }
            )
    return scoped


def request_role_membership_allows(
    request: Any,
    *,
    roles: Iterable[str],
    branch_id: int | None,
    department_id: int | None = None,
) -> bool:
    """Whether one of ``request``'s active memberships covers an object.

    Directors/superusers retain their tenant-wide bypass. For other roles, a
    department-scoped membership never silently expands to its whole branch.
    """
    if is_unscoped(request):
        return True
    return role_memberships_allow(
        get_role_memberships(request),
        roles=roles,
        branch_id=branch_id,
        department_id=department_id,
    )


def role_memberships_allow(
    memberships: Iterable[Any],
    *,
    roles: Iterable[str],
    branch_id: int | None,
    department_id: int | None = None,
) -> bool:
    """Pure membership check shared by request and domain-service boundaries."""
    role_set = set(roles)
    for membership in memberships:
        if membership.role not in role_set or membership.branch_id != branch_id:
            continue
        if membership.department_id is None or membership.department_id == department_id:
            return True
    return False


def assert_in_role_membership_scope(
    request: Any,
    obj: Any,
    *,
    roles: Iterable[str],
    branch_attr: str = "branch_id",
    department_attr: str = "department_id",
) -> None:
    """403 unless ``obj`` is covered by an active branch/department membership."""
    if request_role_membership_allows(
        request,
        roles=roles,
        branch_id=getattr(obj, branch_attr, None),
        department_id=getattr(obj, department_attr, None),
    ):
        return
    from core.exceptions import PermissionException

    raise PermissionException(code="out_of_scope")


def scope_to_branches(request: Any, queryset: QuerySet, *, field: str = "branch_id") -> QuerySet:
    """Filter ``queryset`` to the caller's branches (no-op for an unscoped caller)."""
    if is_unscoped(request):
        return queryset
    return queryset.filter(**{f"{field}__in": branch_ids(request)})


def assert_in_branch_scope(request: Any, obj: Any) -> None:
    """403 if ``obj`` (with ``branch_id``) is outside the caller's branches."""
    if is_unscoped(request):
        return
    if getattr(obj, "branch_id", None) not in branch_ids(request):
        from core.exceptions import PermissionException

        raise PermissionException(code="out_of_scope")


def assert_branch_id_in_scope(request: Any, branch_id: int | None) -> None:
    """403 if ``branch_id`` is outside the caller's branches — for CREATE, where there
    is no object yet (a branch-scoped role must not create rows in another branch)."""
    if is_unscoped(request):
        return
    if branch_id not in branch_ids(request):
        from core.exceptions import PermissionException

        raise PermissionException(code="out_of_scope")
