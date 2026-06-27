from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
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


def _scoped_teachers(request):
    """Teachers whose engagement the caller may see: director/superuser → all; a
    manager (HOD) → their branch(es)' teachers; a teacher → only their own row
    (dignity: a private development signal, not a public leaderboard); anyone else
    → none (fail closed, even with an A-2 intelligence:read grant)."""
    from apps.teachers.models import TeacherProfile
    from apps.teachers.selectors import teacher_profile_for

    base = TeacherProfile.objects.select_related("user")
    roles = get_user_roles(request)
    if request.user.is_superuser or Role.DIRECTOR in roles:
        return base
    if Role.HEAD_OF_DEPT in roles:
        my = {m.branch_id for m in get_role_memberships(request) if m.branch_id and m.role in _STAFF_ROLES}
        return base.filter(branch_id__in=my)
    me = teacher_profile_for(request.user)
    return base.filter(pk=me.pk) if me is not None else base.none()


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


def _is_family(request, student) -> bool:
    """The student themselves, or one of their guardians."""
    if student.user_id == request.user.id:
        return True
    from apps.parents.models import Guardian

    return Guardian.objects.filter(student=student, parent__user=request.user).exists()


class StudentJourneyView(TenantSafeAPIView):
    """GET /api/v1/intelligence/journey/<student_id>/ — one student's chronological
    story (enrollment moves, published grades, achievements, and — finance-gated —
    invoices), newest first. Family-facing: the student and their guardians see their
    own; a STAFF caller must actually hold students:read (so e.g. the IT role, walled
    off academic data everywhere else, can't read it). Invoices need finance:read or
    being the family. 404 if out of scope."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="A student's journey timeline",
        responses={200: OpenApiResponse(description="{student, events:[{at, type, title, detail}]}")},
        tags=["intelligence"],
    )
    def get(self, request, student_id):
        roles = get_user_roles(request)
        student = scoped_students(user=request.user, roles=roles).filter(pk=student_id).first()
        if student is None:
            raise NotFoundException(_("Student not found."), code="not_found")
        overrides = _request_overrides(request)
        is_family = _is_family(request, student)
        # scoped_students alone would admit any STAFF_ROLES member (incl. IT, who is
        # denied student records everywhere else) — require the real read perm for staff.
        if not (
            request.user.is_superuser or is_family or has_permission_code(roles, "students:read", overrides)
        ):
            raise NotFoundException(_("Student not found."), code="not_found")
        include_finance = (
            request.user.is_superuser or is_family or has_permission_code(roles, "finance:read", overrides)
        )
        events = selectors.student_journey(student, include_finance=include_finance)
        return Response({"student": student.id, "events": events})


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


class TeacherEngagementView(TenantSafeAPIView):
    """GET /api/v1/intelligence/teachers/ — per-teacher ENGAGEMENT (attendance in
    their lessons + reach) over the attendance window, best first. Transparent rule,
    NOT causal value-add. Per-teacher named, so it is gated for dignity: a manager
    sees their branch's teachers, a teacher sees only their own row, others none."""

    resource = "intelligence"
    required_perms = {"get": "intelligence:read"}

    @extend_schema(
        summary="Teacher engagement (attendance in their lessons + reach)",
        responses={
            200: OpenApiResponse(
                description="{count, results:[{teacher, name, lessons_delivered, "
                "students_reached, marks_sampled, attendance_rate, engagement_score}], metrics}"
            )
        },
        tags=["intelligence"],
    )
    def get(self, request):
        results = selectors.teacher_engagement(_scoped_teachers(request))
        return Response(
            {"count": len(results), "results": results, "metrics": selectors.TEACHER_METRICS}
        )
