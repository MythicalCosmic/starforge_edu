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
from core.permissions import Role

# Roles that see the whole library regardless of allowed_roles.
_FULL_ROLES = {Role.DIRECTOR}
_DIRECTOR_ONLY_REPORTS = {"ai_usage", "storage_usage"}


def _visible_report_keys(*, user, roles: set[str]) -> set[str] | None:
    """Report keys the caller may see, or None for 'all' (director/superuser)."""
    if getattr(user, "is_superuser", False) or (roles & _FULL_ROLES):
        return None
    keys: set[str] = set()
    for report in Report.objects.all():
        allowed = set(report.allowed_roles or [])
        if roles & allowed and not (report.key in _DIRECTOR_ONLY_REPORTS and Role.DIRECTOR not in roles):
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
    branch_ids = set(
        user.role_memberships.filter(revoked_at__isnull=True).values_list("branch_id", flat=True)
    )
    scope = Q(requested_by=user)
    for branch_id in branch_ids:
        scope |= Q(params___scope_branch_ids__contains=[branch_id])
    return qs.filter(scope, report__key__in=keys).distinct()


def scoped_schedules(*, user, roles: set[str]) -> QuerySet[ReportSchedule]:
    qs = ReportSchedule.objects.select_related("report", "created_by").all()
    keys = _visible_report_keys(user=user, roles=roles)
    if keys is None:
        return qs
    branch_ids = set(
        user.role_memberships.filter(revoked_at__isnull=True).values_list("branch_id", flat=True)
    )
    scope = Q(created_by=user)
    for branch_id in branch_ids:
        scope |= Q(params___scope_branch_ids__contains=[branch_id])
    return qs.filter(scope, report__key__in=keys).distinct()
