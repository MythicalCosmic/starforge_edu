"""Role / permission matrix and DRF permission classes.

Single source of truth: ROLE_PERMISSION_MATRIX maps role -> set of action codes
(`'<resource>:<verb>'`).

TD-4 — fail-closed: a view that declares neither `required_perms[action]` nor a
`resource` from which to derive one is **denied** (never silently allowed).
TD-5 — per-action: views declare `resource = "<name>"` (CRUD verbs derived via
`default_perms`) plus `required_perms = {"<custom_action>": "<resource>:<verb>"}`
for every `@action`.
TD-13 — the active RoleMemberships are fetched once per request and memoized on
`request._role_memberships_cache`, so RolePermission + ObjectScopedPermission
never issue more than one membership query.
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


# Matrix — director sees everything; others see their own resource group. Lanes
# append real per-feature codes as each domain lands (additive edits only).
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
    Role.IT: {"users:read", "audit:read", "org:*"},
    Role.REGISTRAR: {"students:*", "users:write", "cohorts:*", "parents:*", "teachers:read"},
    Role.SUPPORT: {"users:read", "audit:read"},
}


DEFAULT_VERB_FOR_ACTION: dict[str, str] = {
    "list": "read",
    "retrieve": "read",
    "create": "write",
    "update": "write",
    "partial_update": "write",
    "destroy": "write",
}


def default_perms(resource: str) -> dict[str, str]:
    """Standard CRUD permission map for a resource (TD-5).

    Spread into a viewset's `required_perms` and add custom `@action` codes:
    `required_perms = {**default_perms("students"), "transition": "students:write"}`.
    """
    return {action: f"{resource}:{verb}" for action, verb in DEFAULT_VERB_FOR_ACTION.items()}


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


def get_role_memberships(request: Request) -> list:
    """Active RoleMemberships for the request user, fetched once and memoized."""
    cached = getattr(request, "_role_memberships_cache", None)
    if cached is not None:
        return cached
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        memberships: list = []
    else:
        memberships = list(user.role_memberships.filter(revoked_at__isnull=True))
    request._role_memberships_cache = memberships  # type: ignore[attr-defined]
    return memberships


def get_user_roles(request: Request) -> set[str]:
    return {m.role for m in get_role_memberships(request)}


class RolePermission(BasePermission):
    """TD-5 per-action; TD-4 fail-closed: no declaration => deny."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        action = getattr(view, "action", None) or (request.method or "").lower()
        required = (getattr(view, "required_perms", None) or {}).get(action)
        if required is None:
            resource = getattr(view, "resource", None)
            verb = DEFAULT_VERB_FOR_ACTION.get(action)
            if resource is None or verb is None:
                return False  # TD-4: deny, never fall through to permissive default
            required = f"{resource}:{verb}"
        return has_permission_code(get_user_roles(request), required)


class ObjectScopedPermission(BasePermission):
    """Object-level scoping by branch/department.

    Views set `object_scope = "branch" | "department"`; the object exposes
    `branch_id` and/or `department_id`. Director and superuser bypass.
    """

    def has_object_permission(self, request: Request, view: APIView, obj: object) -> bool:
        user = request.user
        if user.is_superuser:
            return True
        memberships = get_role_memberships(request)
        if any(m.role == Role.DIRECTOR for m in memberships):
            return True
        scope = getattr(view, "object_scope", None)
        if scope is None:
            return True
        if scope == "branch":
            allowed = {m.branch_id for m in memberships}
            return getattr(obj, "branch_id", None) in allowed
        if scope == "department":
            allowed = {m.department_id for m in memberships if m.department_id}
            return getattr(obj, "department_id", None) in allowed
        return False
