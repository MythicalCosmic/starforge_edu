"""Intelligence HTTP views (layered, off DRF).

Seven read-only A-3 facets (transparent rules, no black box): dropout-risk list +
detail, branch ranking, family-health retention feed, a student's journey timeline,
the risk rules, and teacher engagement. All are GET. Every facet is scoped in the
view (which students/branches/teachers the caller may see) and rendered from the
preserved apps.intelligence.selectors read layer via IIntelligenceService.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt

from apps.intelligence.interfaces.services import IIntelligenceService
from apps.org.models import Branch
from apps.students.models import StudentProfile
from apps.students.selectors import scoped_students
from core.api_auth import check_perm, require_auth
from core.container import container
from core.exceptions import NotFoundException, PermissionException, ValidationException
from core.listing import paginate_sequence
from core.permissions import (
    Role,
    _request_overrides,
    get_user_roles,
    has_permission_code,
)
from core.responses import error, success
from core.scoping import permission_membership_scope_q, permission_membership_scopes

# Only STAFF memberships grant a branch scope for the intelligence facets — a
# student/parent membership must never (e.g. via an A-2 grant of intelligence:read)
# resolve to a branch and open the branch-level feeds. This fails closed for them.


def _service() -> IIntelligenceService:
    return container.resolve(IIntelligenceService)  # type: ignore[type-abstract]


def _method_not_allowed() -> HttpResponse:
    return error("Method not allowed.", code="method_not_allowed", status=405)


def _page_results(request: HttpRequest, payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results", [])
    rows, total, page, page_size = paginate_sequence(request, results)
    return {
        **payload,
        "count": total,
        "results": rows,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


def _can_see_finance(request: HttpRequest) -> bool:
    """Whether to include the overdue-payment flag — only callers who may see
    finance (finance:read / superuser) get the financial signal."""
    req: Any = request  # perm helpers are duck-typed on .user (typed Request upstream)
    if req.user.is_superuser:
        return True
    roles = get_user_roles(req)
    if Role.DIRECTOR in roles:
        return True
    if not has_permission_code(roles, "finance:read", _request_overrides(req)):
        return False

    # The selector accepts one finance flag for the entire result set. Require
    # finance scope to cover every intelligence scope so a grant in Branch B
    # cannot expose overdue-payment flags for Branch A.
    intelligence_scopes = permission_membership_scopes(
        roles=roles,
        permission="intelligence:read",
        account_kinds={"staff", "teacher"},
    )
    finance_scopes = permission_membership_scopes(
        roles=roles,
        permission="finance:read",
        account_kinds={"staff", "teacher"},
    )
    return bool(intelligence_scopes) and all(
        any(
            finance.branch_id == intelligence.branch_id
            and (finance.department_id is None or finance.department_id == intelligence.department_id)
            for finance in finance_scopes
        )
        for intelligence in intelligence_scopes
    )


def _scoped_branches(request: HttpRequest):
    """Branches the caller may rank: the director/superuser sees every (live) branch,
    a branch-scoped STAFF role sees only the branch(es) they belong to, non-staff none."""
    qs = Branch.objects.filter(archived_at__isnull=True)
    roles = get_user_roles(request)
    if request.user.is_superuser or Role.DIRECTOR in roles:
        return qs
    return qs.filter(
        permission_membership_scope_q(
            roles=roles,
            permission="intelligence:read",
            branch_field="id",
            account_kinds={"staff", "teacher"},
        )
    )


def _scoped_teachers(request: HttpRequest):
    """Teachers whose engagement the caller may see: director/superuser → all; a
    manager (HOD) → their branch(es)' teachers; a teacher → only their own row;
    anyone else → none (fail closed, even with an A-2 intelligence:read grant)."""
    from apps.teachers.models import TeacherProfile
    from apps.teachers.selectors import teacher_profile_for

    base = TeacherProfile.objects.select_related("user")
    roles = get_user_roles(request)
    if request.user.is_superuser or Role.DIRECTOR in roles:
        return base
    staff_scope = permission_membership_scope_q(
        roles=roles,
        permission="intelligence:read",
        branch_field="branch_id",
        department_field="department_id",
        account_kinds={"staff"},
    )
    me = teacher_profile_for(request.user)
    teacher_scope = permission_membership_scopes(
        roles=roles,
        permission="intelligence:read",
        account_kinds={"teacher"},
    )
    own_scope = Q(pk=me.pk) if me is not None and teacher_scope else Q(pk__in=[])
    return base.filter(staff_scope | own_scope).distinct()


def _is_family(request: HttpRequest, student) -> bool:
    """The student themselves, or one of their guardians."""
    user: Any = request.user
    if student.user_id == user.id:
        return True
    from apps.parents.models import Guardian

    return Guardian.objects.filter(student=student, parent__user=user).exists()


def _scoped_risk_students(request: HttpRequest):
    """Student scope for named risk data.

    General staff readers stay branch/department scoped through ``scoped_students``.
    A teacher without a management membership is narrower still: only cohorts they
    actually teach through a typed assignment, legacy primary assignment, or lesson.
    """
    from apps.cohorts.selectors import taught_cohorts

    roles = get_user_roles(request)
    qs = StudentProfile.objects.select_related("user", "branch", "current_cohort")
    if request.user.is_superuser or Role.DIRECTOR in roles:
        return qs
    visible = permission_membership_scope_q(
        roles=roles,
        permission="intelligence:read",
        branch_field="branch_id",
        department_field="current_cohort__department_id",
        account_kinds={"staff"},
    )
    teacher_scope = permission_membership_scopes(
        roles=roles,
        permission="intelligence:read",
        account_kinds={"teacher"},
    )
    if teacher_scope:
        visible |= Q(current_cohort__in=taught_cohorts(user=request.user))
    return qs.filter(visible).distinct()


@csrf_exempt
@require_auth
def risk_list_view(request: HttpRequest) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return _method_not_allowed()
    check_perm(request, "intelligence:read")
    qs = _scoped_risk_students(request)
    cohort = request.GET.get("cohort")
    if cohort:
        try:
            cohort_id = int(cohort)
        except ValueError:
            raise ValidationException(
                "Invalid query parameter.",
                code="invalid_query_param",
                fields={"cohort": ["Must be an integer."]},
            ) from None
        qs = qs.filter(current_cohort_id=cohort_id)
    return success(
        _page_results(
            request,
            _service().risk_list(students=qs, include_finance=_can_see_finance(request)),
        )
    )


@csrf_exempt
@require_auth
def risk_detail_view(request: HttpRequest, student_id: int) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return _method_not_allowed()
    check_perm(request, "intelligence:read")
    student = _scoped_risk_students(request).filter(pk=student_id).first()
    if student is None:
        raise NotFoundException(_("Student not found."), code="not_found")
    return success(_service().risk_detail(student=student, include_finance=_can_see_finance(request)))


@csrf_exempt
@require_auth
def branch_ranking_view(request: HttpRequest) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return _method_not_allowed()
    check_perm(request, "intelligence:read")
    return success(
        _page_results(
            request,
            _service().branch_ranking(
                branches=_scoped_branches(request), include_finance=_can_see_finance(request)
            ),
        )
    )


@csrf_exempt
@require_auth
def family_health_view(request: HttpRequest) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return _method_not_allowed()
    check_perm(request, "intelligence:read")
    # Naming a family + surfacing their children's risk needs family-record
    # visibility — gate out teachers (intelligence:read but no parents:read).
    req: Any = request  # perm helpers are duck-typed on .user (typed Request upstream)
    if not (
        req.user.is_superuser
        or has_permission_code(get_user_roles(req), "parents:read", _request_overrides(req))
    ):
        raise PermissionException(
            _("Family health needs visibility of family records."), code="not_permitted"
        )
    return success(
        _page_results(
            request,
            _service().family_health(
                branches=_scoped_branches(request), include_finance=_can_see_finance(request)
            ),
        )
    )


@csrf_exempt
@require_auth
def student_journey_view(request: HttpRequest, student_id: int) -> HttpResponse:
    """Family-facing timeline: the student + their guardians see their own; a STAFF
    caller must actually hold students:read (so e.g. IT, walled off academic data
    everywhere else, can't read it). Invoices need finance:read or being the family."""
    if request.method not in ("GET", "HEAD"):
        return _method_not_allowed()
    req: Any = request  # perm helpers are duck-typed on .user (typed Request upstream)
    roles = get_user_roles(req)
    student = scoped_students(user=request.user, roles=roles).filter(pk=student_id).first()
    if student is None:
        raise NotFoundException(_("Student not found."), code="not_found")
    overrides = _request_overrides(req)
    is_family = _is_family(request, student)
    # scoped_students alone would admit any STAFF_ROLES member (incl. IT) — require the
    # real read perm for staff; an out-of-scope caller gets 404 (no existence leak).
    if not (request.user.is_superuser or is_family or has_permission_code(roles, "students:read", overrides)):
        raise NotFoundException(_("Student not found."), code="not_found")
    include_finance = (
        request.user.is_superuser or is_family or has_permission_code(roles, "finance:read", overrides)
    )
    return success(_service().student_journey(student=student, include_finance=include_finance))


@csrf_exempt
@require_auth
def rules_view(request: HttpRequest) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return _method_not_allowed()
    check_perm(request, "intelligence:read")
    return success(_service().rules())


@csrf_exempt
@require_auth
def teacher_engagement_view(request: HttpRequest) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return _method_not_allowed()
    check_perm(request, "intelligence:read")
    return success(_page_results(request, _service().teacher_engagement(teachers=_scoped_teachers(request))))
