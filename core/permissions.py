"""Role / permission matrix and DRF permission classes.

Single source of truth: ROLE_PERMISSION_MATRIX maps role -> set of action codes
(`'<resource>:<verb>'`). The RolePermission DRF class consults this matrix on
each request; ObjectScopedPermission additionally checks branch/department
scoping when a view declares `object_scope = "branch" | "department"`.

Real role assignments live on RoleMembership(user, branch, department, role)
in apps.users.models. v1 permissions are intentionally coarse — refine per
feature when the workflow is actually built.
"""

from __future__ import annotations

from collections.abc import Iterable

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class Role:
    DIRECTOR = "director"
    HEAD_OF_DEPT = "head_of_dept"
    TEACHER = "teacher"
    STUDENT = "student"
    PARENT = "parent"
    ACCOUNTANT = "accountant"
    CASHIER = "cashier"
    LIBRARIAN = "librarian"
    SECURITY = "security"
    IT = "it"
    REGISTRAR = "registrar"
    SUPPORT = "support"

    ALL = (
        DIRECTOR,
        HEAD_OF_DEPT,
        TEACHER,
        STUDENT,
        PARENT,
        ACCOUNTANT,
        CASHIER,
        LIBRARIAN,
        SECURITY,
        IT,
        REGISTRAR,
        SUPPORT,
    )


# Stub matrix — director sees everything, others see their own resource
# group only. Refine per-feature when wiring the actual ViewSets.
ROLE_PERMISSION_MATRIX: dict[str, set[str]] = {
    Role.DIRECTOR: {"*:*"},
    Role.HEAD_OF_DEPT: {
        "users:read",
        "students:*",
        "teachers:read",
        "cohorts:*",
        "attendance:*",
        "academics:*",
        "assignments:*",
        "schedule:*",
        "reports:read",
        "audit:read",
    },
    Role.TEACHER: {
        "students:read",
        "cohorts:read",
        "attendance:*",
        "academics:write",
        "assignments:*",
        "schedule:read",
        "content:*",
    },
    Role.STUDENT: {
        "schedule:read",
        "attendance:read_self",
        "academics:read_self",
        "assignments:read",
        "content:read",
    },
    Role.PARENT: {
        "students:read_own_children",
        "attendance:read_own_children",
        "academics:read_own_children",
        "finance:read_own",
        "schedule:read",
        "notifications:read",
    },
    Role.ACCOUNTANT: {"finance:*", "payments:*", "reports:read"},
    Role.CASHIER: {"finance:read", "payments:write"},
    Role.LIBRARIAN: {"content:*", "students:read", "cohorts:read"},
    Role.SECURITY: {"attendance:write", "users:read"},
    Role.IT: {"users:read", "audit:read"},
    Role.REGISTRAR: {"students:*", "users:write", "cohorts:*"},
    Role.SUPPORT: {"users:read", "audit:read"},
}


def has_permission_code(roles: Iterable[str], code: str) -> bool:
    resource, _, _verb = code.partition(":")
    for role in roles:
        perms = ROLE_PERMISSION_MATRIX.get(role, set())
        if "*:*" in perms:
            return True
        if f"{resource}:*" in perms:
            return True
        if code in perms:
            return True
    return False


class RolePermission(BasePermission):
    """Per-action permission. Views declare `required_perm = 'resource:verb'`."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        required = getattr(view, "required_perm", None)
        if required is None:
            return True  # view didn't declare; falls back to IsAuthenticated default
        roles = _user_roles(user)
        return has_permission_code(roles, required)


class ObjectScopedPermission(BasePermission):
    """Object-level scoping by branch/department.

    Views set `object_scope = "branch" | "department"`. The object is expected
    to expose `branch_id` and/or `department_id`. Director and superuser bypass.
    """

    def has_object_permission(self, request: Request, view: APIView, obj: object) -> bool:
        user = request.user
        if user.is_superuser:
            return True
        if Role.DIRECTOR in _user_roles(user):
            return True
        scope = getattr(view, "object_scope", None)
        if scope is None:
            return True
        memberships = getattr(user, "role_memberships", None)
        if memberships is None:
            return False
        if scope == "branch":
            allowed = {m.branch_id for m in memberships.all()}
            return getattr(obj, "branch_id", None) in allowed
        if scope == "department":
            allowed = {m.department_id for m in memberships.all() if m.department_id}
            return getattr(obj, "department_id", None) in allowed
        return False


def _user_roles(user: object) -> set[str]:
    memberships = getattr(user, "role_memberships", None)
    if memberships is None:
        return set()
    return {m.role for m in memberships.all()}
