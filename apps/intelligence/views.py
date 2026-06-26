from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response

from apps.intelligence import selectors
from apps.org.models import Branch
from apps.students.selectors import scoped_students
from core.exceptions import NotFoundException, PermissionException
from core.permissions import (
    Role,
    _request_overrides,
    get_role_memberships,
    get_user_roles,
    has_permission_code,
)
from core.viewsets import TenantSafeAPIView


def _can_see_finance(request) -> bool:
    """Whether to include the overdue-payment flag — only callers who may see
    finance (finance:read / superuser) get the financial signal."""
    return request.user.is_superuser or has_permission_code(
        get_user_roles(request), "finance:read", _request_overrides(request)
    )


# Only STAFF memberships grant a branch scope for the intelligence facets — a
# student/parent membership must never (e.g. via an A-2 grant of intelligence:read)
# resolve to a branch and open the branch-level feeds. This fails closed for them.
_STAFF_ROLES = frozenset(r for r in Role.ALL if r not in (Role.STUDENT, Role.PARENT))


def _scoped_branches(request):
    """Branches the caller may rank: the director/superuser sees every (live) branch
    — the multi-branch owner's whole estate — while a branch-scoped STAFF role sees
    only the branch(es) they belong to. Non-staff callers resolve to no branches."""
    qs = Branch.objects.filter(archived_at__isnull=True)
    if request.user.is_superuser or Role.DIRECTOR in get_user_roles(request):
        return qs
    my = {m.branch_id for m in get_role_memberships(request) if m.branch_id and m.role in _STAFF_ROLES}
    return qs.filter(id__in=my)


class RiskListView(TenantSafeAPIView):
    """GET /api/v1/intelligence/risk/ — at-risk students in the caller's scope
    (optionally ?cohort=<id>), highest risk first. Transparent rules only (A-3)."""

    resource = "intelligence"
    required_perms = {"get": "intelligence:read"}

    @extend_schema(
        summary="At-risk students (dropout-risk flags)",
        parameters=[OpenApiParameter("cohort", int, description="restrict to one cohort")],
        responses={200: OpenApiResponse(description="{count, results:[{student, score, level, flags}]}")},
        tags=["intelligence"],
    )
    def get(self, request):
        qs = scoped_students(user=request.user, roles=get_user_roles(request)).select_related("user")
        cohort = request.query_params.get("cohort")
        if cohort:
            qs = qs.filter(current_cohort_id=cohort)
        results = selectors.student_risk(qs, include_finance=_can_see_finance(request))
        return Response({"count": len(results), "results": results})


class RiskDetailView(TenantSafeAPIView):
    """GET /api/v1/intelligence/risk/<student_id>/ — one student's full risk picture
    (the flags it fires, or a 'none' result), for the transparency 'why is this
    student flagged' view. 404 if the student isn't in the caller's scope."""

    resource = "intelligence"
    required_perms = {"get": "intelligence:read"}

    @extend_schema(
        summary="One student's risk detail",
        responses={200: OpenApiResponse(description="risk object"), 404: OpenApiResponse()},
        tags=["intelligence"],
    )
    def get(self, request, student_id):
        student = (
            scoped_students(user=request.user, roles=get_user_roles(request))
            .select_related("user")
            .filter(pk=student_id)
            .first()
        )
        if student is None:
            raise NotFoundException(_("Student not found."), code="not_found")
        return Response(selectors.student_risk_detail(student, include_finance=_can_see_finance(request)))


class BranchRankingView(TenantSafeAPIView):
    """GET /api/v1/intelligence/branches/ — branch performance ranking (A-3 facet):
    each branch in the caller's scope scored 0-100 over attendance, published grades,
    and dropout-risk, highest first. Transparent weights only (no black box). Branch-
    level metrics; a branch too small to anonymise (< MIN_BRANCH_CELL active students)
    is suppressed, and the overdue count is finance-gated. The score is computed
    without the overdue signal for callers who can't see finance, so `method` discloses
    `includes_finance` — scores aren't comparable across roles with different finance
    visibility."""

    resource = "intelligence"
    required_perms = {"get": "intelligence:read"}

    @extend_schema(
        summary="Branch performance ranking",
        responses={200: OpenApiResponse(description="{count, method, results:[{branch, score, rank, ...}]}")},
        tags=["intelligence"],
    )
    def get(self, request):
        include_finance = _can_see_finance(request)
        results = selectors.branch_ranking(_scoped_branches(request), include_finance=include_finance)
        return Response(
            {
                "count": len(results),
                "method": {
                    "metrics": selectors.BRANCH_METRICS,
                    "score_range": "0-100",
                    "min_cell_size": selectors.MIN_BRANCH_CELL,
                    "includes_finance": include_finance,
                },
                "results": results,
            }
        )


class FamilyHealthView(TenantSafeAPIView):
    """GET /api/v1/intelligence/families/ — the retention desk's family-health feed
    (A-3 facet): each family (a guardian + the children they guard, in the caller's
    branch scope) flagged good/watch/at_risk so the centre can call before a family
    leaves. Worst first. Deliberately per-family (NOT anonymised — the point is to name
    who to follow up), so it is double-gated: intelligence:read AND parents:read (the
    retention desk, never teachers or parents themselves). Overdue is finance-gated."""

    resource = "intelligence"
    required_perms = {"get": "intelligence:read"}

    @extend_schema(
        summary="Family-health retention feed",
        responses={200: OpenApiResponse(description="{count, levels, results:[{family, health, ...}]}")},
        tags=["intelligence"],
    )
    def get(self, request):
        # Naming a family + surfacing their children's risk needs family-record
        # visibility — gate out teachers (intelligence:read but no parents:read).
        if not (
            request.user.is_superuser
            or has_permission_code(get_user_roles(request), "parents:read", _request_overrides(request))
        ):
            raise PermissionException(
                _("Family health needs visibility of family records."), code="not_permitted"
            )
        results = selectors.family_health(
            _scoped_branches(request), include_finance=_can_see_finance(request)
        )
        return Response({"count": len(results), "levels": selectors.FAMILY_HEALTH_LEVELS, "results": results})


class RulesView(TenantSafeAPIView):
    """GET /api/v1/intelligence/rules/ — the exact rules + thresholds that drive the
    flags (no black box: a center can see precisely how risk is computed)."""

    resource = "intelligence"
    required_perms = {"get": "intelligence:read"}

    @extend_schema(
        summary="The transparent risk rules + thresholds",
        responses={200: OpenApiResponse(description="{rules, thresholds, levels}")},
        tags=["intelligence"],
    )
    def get(self, request):
        return Response(
            {
                "rules": selectors.RULES,
                "thresholds": {
                    "attendance_window_days": selectors.ATTENDANCE_WINDOW_DAYS,
                    "min_lessons": selectors.MIN_LESSONS_FOR_ATTENDANCE_FLAG,
                    "absence_rate": selectors.ABSENCE_RATE_THRESHOLD,
                    "low_grade_pct": selectors.LOW_GRADE_PCT_THRESHOLD,
                },
                "levels": {"low": "1-2", "medium": "3-4", "high": "5+"},
            }
        )
