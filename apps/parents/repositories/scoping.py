"""Shared row-level scoping for the parent domain (TD-5).

Director sees every row. Other staff are constrained by active branch/department
memberships, while a parent sees only their own rows (via ``own_filter``).
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from core.permissions import Role
from core.scoping import role_membership_scope_q

SCOPED_STAFF_ROLES = frozenset({Role.HEAD_OF_DEPT, Role.REGISTRAR, Role.IT})


def scope_rows(
    qs: QuerySet,
    *,
    user,
    roles,
    own_filter: dict,
    branch_field: str,
    department_field: str,
) -> QuerySet:
    if getattr(user, "is_superuser", False):
        return qs
    role_set = set(roles or ())
    if Role.DIRECTOR in role_set:
        return qs

    visible = Q(pk__in=[])
    scoped_staff = role_set & SCOPED_STAFF_ROLES
    if scoped_staff:
        visible |= role_membership_scope_q(
            user=user,
            roles=scoped_staff,
            branch_field=branch_field,
            department_field=department_field,
        )
    if Role.PARENT in role_set:
        visible |= Q(**own_filter)
    return qs.filter(visible).distinct()
