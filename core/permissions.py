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
        "reports:write",  # D4-LB-5
        "audit:read",
        # D4-LA-8: AI request log + budget snapshot + exam generation (read+write).
        # ai:manage (budget edits) stays director-only via *:*.
        "ai:read",
        "ai:write",
        "printing:read",  # D4-LD-7
        "printing:write",
        # A-1: HOD is a manager-level approver (request + approve, not disburse).
        "approvals:read",
        "approvals:write",
        "approvals:approve",
        # #12: HOD can author + see the rule book.
        "compliance:read",
        "compliance:write",
    },
    Role.TEACHER: {
        "students:read",
        "cohorts:read",
        # D1-LB-3 / D1-LF-8 acceptance: teachers read org structure (branches,
        # rooms, working hours, settings knobs) — never write it.
        "org:read",
        "attendance:*",
        "academics:read",  # D2-C-7: pairs with academics:write (Day-1 asymmetry fix)
        "academics:write",
        "assignments:*",
        "schedule:read",
        "content:*",
        # D4-LA-8: teachers read the AI log + request exam generation (ai:write).
        "ai:read",
        "ai:write",
        "reports:read",  # D4-LB-5: run own-cohort enrollment/attendance/grades reports
        "reports:write",
        "printing:read",  # D4-LD-7: request prints
        "printing:write",
        # A-1: teachers can raise requests (expense/loan/discount/salary-prep).
        "approvals:read",
        "approvals:write",
    },
    Role.STUDENT: {
        # students:read is row-scoped to self by apps/students/selectors.py
        # (read_self semantics live in selectors, not the gate — TD-5).
        "students:read",
        "schedule:read",
        "attendance:read",  # row-scoped to self in apps/attendance/selectors.py
        "academics:read",  # row-scoped to self + publication gate in apps/academics/selectors.py
        "assignments:read",
        "assignments:submit",  # D2-D-6: students submit their own work
        "content:read",
    },
    Role.PARENT: {
        # Row-scoped by selectors: students -> guardian-linked children only,
        # parents -> own profile only (TD-5 read_own_children semantics).
        "students:read",
        "parents:read",
        "students:read_own_children",
        "attendance:read",  # row-scoped to guardian-linked children in selectors
        "academics:read",  # row-scoped to children + publication gate in selectors
        "content:read",  # row-scoped to children's cohorts via apps/content/selectors._related_cohort_ids
        "finance:read_own",
        "schedule:read",
        "notifications:read",
    },
    Role.ACCOUNTANT: {
        "finance:*",
        "payments:*",
        "reports:read",
        "reports:write",
        # A-1: accountant requests, approves, disburses, and reads the ledger.
        "approvals:read",
        "approvals:write",
        "approvals:approve",
        "approvals:disburse",
        "ledger:read",
    },
    # A-1: the cashier disburses approved requests + reads the ledger (the till).
    Role.CASHIER: {"finance:read", "payments:write", "approvals:read", "approvals:disburse", "ledger:read"},
    Role.LIBRARIAN: {"content:*", "students:read", "cohorts:read"},
    Role.SECURITY: {"attendance:write", "users:read"},
    Role.IT: {"users:read", "audit:read", "org:*", "compliance:read", "compliance:write"},
    Role.REGISTRAR: {
        "students:*",
        "users:write",
        "cohorts:*",
        "parents:*",
        "teachers:read",
        "schedule:*",
        "printing:read",  # D4-LD-7: manage printers/agents
        "printing:write",
        # A-1: reception can raise requests too.
        "approvals:read",
        "approvals:write",
    },
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


def _load_tenant_overrides() -> dict[str, dict[str, str]]:
    """`{role: {permission: effect}}` for the active tenant (A-2). One small query
    over the (tiny) override table. Empty on the public schema (the table is
    tenant-only) or if it is not yet migrated, so the static matrix always governs
    as a safe fallback. Loaded once per request (memoized on the request by the
    permission classes) — there is no cross-request cache, so a grant/revoke takes
    effect on the very next request with no staleness window."""
    from django_tenants.utils import get_public_schema_name

    from core.utils import current_schema

    if current_schema() == get_public_schema_name():
        return {}
    # The override table is in TENANT_APPS, so it exists in every migrated tenant
    # schema — the only way it is absent is pre-migration, which never coincides
    # with request-flow permission checks. So we read it directly (one cheap SELECT,
    # no per-request savepoint overhead); a genuinely missing table would surface
    # loudly as a setup error rather than being silently swallowed.
    out: dict[str, dict[str, str]] = {}
    from apps.access.models import RolePermissionOverride

    for ov in RolePermissionOverride.objects.all().only("role", "permission", "effect"):
        out.setdefault(ov.role, {})[ov.permission] = ov.effect
    return out


def _request_overrides(request: Request) -> dict[str, dict[str, str]]:
    """The override map, fetched once per request and memoized (mirrors
    get_role_memberships) so multiple permission checks share a single query."""
    cached = getattr(request, "_perm_overrides_cache", None)
    if cached is None:
        cached = _load_tenant_overrides()
        request._perm_overrides_cache = cached  # type: ignore[attr-defined]
    return cached


def _role_grant_revoke(role: str, overrides: dict[str, dict[str, str]]) -> tuple[set[str], set[str]]:
    """`(granted, revoked)` permission-code sets for `role`: the static matrix plus
    this tenant's grant overrides, and the revoke overrides kept separate (they are
    applied at match time so they can override a resource-wildcard grant)."""
    granted = set(ROLE_PERMISSION_MATRIX.get(role, set()))
    revoked: set[str] = set()
    for permission, effect in overrides.get(role, {}).items():
        (granted if effect == "grant" else revoked).add(permission)
    return granted, revoked


def _code_allowed(granted: set[str], revoked: set[str], code: str) -> bool:
    """Does `(granted, revoked)` authorize `code`?

    The master wildcard `*:*` is absolute and revoke-immune (a director keeping it
    can never be locked out). Otherwise a revoke — exact OR the covering
    resource-wildcard — denies the code even when a resource-wildcard grant would
    cover it, so a center can genuinely carve a verb out of a wildcard role. A grant
    then allows via exact code or the resource-wildcard.
    """
    if "*:*" in granted:
        return True
    resource, _, _verb = code.partition(":")
    if code in revoked or f"{resource}:*" in revoked:
        return False
    return f"{resource}:*" in granted or code in granted


def role_effective_permissions(
    role: str, overrides: dict[str, dict[str, str]] | None = None
) -> dict[str, list[str]]:
    """`{"granted": [...], "revoked": [...]}` for `role` with this tenant's overrides
    applied — the honest representation for the admin UI (a revoke can scope a verb
    out of a wildcard grant, which a single flat set could not express)."""
    if overrides is None:
        overrides = _load_tenant_overrides()
    granted, revoked = _role_grant_revoke(role, overrides)
    return {"granted": sorted(granted), "revoked": sorted(revoked)}


def roles_with_permission(code: str, overrides: dict[str, dict[str, str]] | None = None) -> set[str]:
    """Every role whose EFFECTIVE permissions authorize `code` (overrides included).
    Used to find notification recipients for a permission (e.g. who can disburse)."""
    if overrides is None:
        overrides = _load_tenant_overrides()
    out: set[str] = set()
    for role in ROLE_PERMISSION_MATRIX:
        granted, revoked = _role_grant_revoke(role, overrides)
        if _code_allowed(granted, revoked, code):
            out.add(role)
    return out


def has_permission_code(
    roles: Iterable[str], code: str, overrides: dict[str, dict[str, str]] | None = None
) -> bool:
    if overrides is None:
        overrides = _load_tenant_overrides()
    for role in roles:
        granted, revoked = _role_grant_revoke(role, overrides)
        if _code_allowed(granted, revoked, code):
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
        return has_permission_code(get_user_roles(request), required, _request_overrides(request))


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


SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def is_read_only_token(request: Request) -> bool:
    """True when the request is authenticated by a read-only impersonation token
    (access claim ``read_only=true``). Surfaced by the JWT auth class as
    ``request.is_read_only_token``; falls back to the raw ``request.auth`` claim."""
    read_only = bool(getattr(request, "is_read_only_token", False))
    if not read_only:
        auth = getattr(request, "auth", None)
        try:
            read_only = bool(auth.get("read_only")) if auth is not None else False
        except AttributeError:
            read_only = False
    return read_only


class DenyWriteForReadOnlyToken(BasePermission):
    """D4-LE-4: a read-only impersonation token (claim ``read_only=true``) may make
    only SAFE (GET/HEAD/OPTIONS) requests. Any write → 403 ``read_only_token``.
    Normal tokens (no claim) are unaffected.

    NOTE: this only covers views that include it in ``permission_classes``. The
    authoritative, opt-out-proof enforcement lives in ``core.viewsets`` (both base
    classes call ``assert_not_read_only_write`` in ``initial``) so an APIView that
    overrides ``permission_classes`` can never silently regain write access."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return True
        if is_read_only_token(request):
            from core.exceptions import PermissionException

            raise PermissionException(code="read_only_token")
        return True
