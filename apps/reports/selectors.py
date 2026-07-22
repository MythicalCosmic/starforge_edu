"""Reports read-side selectors (D4-LB-5).

Library + run + schedule visibility is role-scoped HERE (not in the view): a
director sees the whole library; an accountant sees only ``finance``; a teacher
sees ``enrollment``/``attendance``/``grades`` (cohort row-scoping inside the
generators). Runs/schedules a caller can see are limited to the reports their
roles can run.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.reports.models import Report, ReportRun, ReportSchedule
from core.permissions import PermissionRoleSet, Role, _code_allowed, has_permission_code

# Roles that see the whole library regardless of allowed_roles.
_FULL_ROLES = {Role.DIRECTOR}
_DIRECTOR_ONLY_REPORTS = {"ai_usage", "storage_usage"}
_REPORT_DOMAIN_PERMISSION = {
    "enrollment": "students:read",
    "attendance": "attendance:read",
    "grades": "academics:read",
    "finance": "finance:read",
}


def _visible_report_keys(*, user, roles: set[str]) -> set[str] | None:
    """Report keys the caller may see, or None for 'all' (director/superuser)."""
    if getattr(user, "is_superuser", False) or (roles & _FULL_ROLES):
        return None
    keys: set[str] = set()
    legacy_roles = roles.fallback_roles if isinstance(roles, PermissionRoleSet) else roles
    for report in Report.objects.all():
        allowed = set(report.allowed_roles or [])
        legacy_visible = bool(legacy_roles & allowed)
        custom_visible = (
            isinstance(roles, PermissionRoleSet)
            and has_permission_code(roles, "reports:read", {})
            and has_permission_code(roles, _REPORT_DOMAIN_PERMISSION.get(report.key, "*:*"), {})
        )
        if (legacy_visible or custom_visible) and not (
            report.key in _DIRECTOR_ONLY_REPORTS and Role.DIRECTOR not in roles
        ):
            keys.add(report.key)
    return keys


def scoped_reports(*, user, roles: set[str]) -> QuerySet[Report]:
    """The library entries visible to the caller (filtered by allowed_roles)."""
    qs = Report.objects.all()
    keys = _visible_report_keys(user=user, roles=roles)
    if keys is None:
        return qs
    return qs.filter(key__in=keys)


def scoped_runs(*, user, roles: set[str]) -> QuerySet[ReportRun]:
    """Runs the caller may see: own or explicitly in one of their branches.

    Report-type permission alone is never object scope: two teachers allowed to
    run attendance reports must not thereby download each other's output.
    """
    qs = ReportRun.objects.select_related("report", "requested_by").all()
    keys = _visible_report_keys(user=user, roles=roles)
    if keys is None:
        return qs
    branch_ids = _report_branch_ids(user=user, roles=roles)
    scope = Q(requested_by=user)
    for branch_id in branch_ids:
        scope |= Q(params___scope_branch_ids__contains=[branch_id])
    return qs.filter(scope, report__key__in=keys).distinct()


def scoped_schedules(*, user, roles: set[str]) -> QuerySet[ReportSchedule]:
    qs = ReportSchedule.objects.select_related("report", "created_by").all()
    keys = _visible_report_keys(user=user, roles=roles)
    if keys is None:
        return qs
    branch_ids = _report_branch_ids(user=user, roles=roles)
    scope = Q(created_by=user)
    for branch_id in branch_ids:
        scope |= Q(params___scope_branch_ids__contains=[branch_id])
    return qs.filter(scope, report__key__in=keys).distinct()


def _report_branch_ids(*, user, roles: set[str]) -> set[int]:
    if isinstance(roles, PermissionRoleSet):
        branch_ids: set[int] = set()
        for membership in roles.membership_scopes:
            if membership.account_kind not in {"staff", "teacher"}:
                continue
            if membership.is_legacy_fallback:
                allowed = has_permission_code({membership.role}, "reports:read") or has_permission_code(
                    {membership.role}, "reports:write"
                )
            else:
                allowed = _code_allowed(set(membership.grants), set(), "reports:read") or _code_allowed(
                    set(membership.grants), set(), "reports:write"
                )
            if allowed:
                branch_ids.add(membership.branch_id)
        return branch_ids
    return set(
        user.role_memberships.filter(revoked_at__isnull=True)
        .filter(Q(account_type__isnull=True) | Q(account_type__is_active=True))
        .values_list("branch_id", flat=True)
    )
