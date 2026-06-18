"""Student read selectors with role-based scoping (TD-5)."""

from __future__ import annotations

from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.students.models import EnrollmentEvent, StudentProfile
from core.permissions import Role

# What counts as "leaving" the center (for joined/left analytics).
_LEFT_STATUSES = (StudentProfile.Status.WITHDRAWN, StudentProfile.Status.GRADUATED)
_COMPARISON_UNITS = ("hour", "day", "week", "month", "year")

# Roles that see every student in the tenant.
STAFF_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT, Role.TEACHER, Role.REGISTRAR, Role.IT}


def _base_qs() -> QuerySet[StudentProfile]:
    return StudentProfile.objects.select_related("user", "branch", "current_cohort")


def scoped_students(*, user, roles: set[str] | None = None) -> QuerySet[StudentProfile]:
    qs = _base_qs()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if roles & STAFF_ROLES:
        return qs
    if Role.PARENT in roles:  # read_own_children
        return qs.filter(guardians__parent__user=user).distinct()
    if Role.STUDENT in roles:  # read_self
        return qs.filter(user=user)
    return qs.none()  # fail closed


def students_with_upcoming_birthdays(
    *, base: QuerySet[StudentProfile] | None = None, days: int = 7, branch=None, cohort=None
) -> QuerySet[StudentProfile]:
    today = timezone.now().date()
    # Clamp defensively: the (month, day) set is exhaustive at 366 days anyway,
    # so capping is semantically lossless and protects future callers.
    month_days = {
        (today + timedelta(days=offset)).timetuple()[1:3] for offset in range(min(max(days, 0), 366) + 1)
    }
    window = Q()
    for month, day in month_days:
        window |= Q(user__birthdate__month=month, user__birthdate__day=day)
    qs = (base if base is not None else _base_qs()).filter(user__birthdate__isnull=False).filter(window)
    if branch:
        qs = qs.filter(branch_id=branch)
    if cohort:
        qs = qs.filter(current_cohort_id=cohort)
    return qs


def student_stats(qs: QuerySet[StudentProfile]) -> dict:
    """Snapshot counts over an already-scoped student queryset (F2-4).

    Three aggregate queries total — counts, by-status, by-branch — so it stays
    cheap regardless of student count.
    """
    total = qs.count()
    with_cohort = qs.filter(current_cohort__isnull=False).count()
    blocked = qs.filter(blocked_at__isnull=False).count()
    by_status = {row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))}
    by_branch = {
        row["branch__name"]: row["n"]
        for row in qs.values("branch__name").annotate(n=Count("id")).order_by("-n")
    }
    return {
        "total": total,
        "with_cohort": with_cohort,
        "without_cohort": total - with_cohort,
        "blocked": blocked,
        "by_status": by_status,
        "by_branch": by_branch,
    }


def _unit_delta(unit: str):
    return {
        "hour": timedelta(hours=1),
        "day": timedelta(days=1),
        "week": timedelta(weeks=1),
        "month": relativedelta(months=1),
        "year": relativedelta(years=1),
    }[unit]


def student_comparison(qs: QuerySet[StudentProfile], *, metric: str, unit: str) -> dict:
    """Compare a metric this period vs the previous one (F2-5).

    metric="joined" counts new student records (StudentProfile.created_at);
    metric="left" counts withdrawn/graduated transitions (EnrollmentEvent). Both
    timestamps are datetimes, so unit="hour" is meaningful. `qs` is the caller's
    role-scoped student queryset (the comparison respects visibility).
    """
    now = timezone.now()
    delta = _unit_delta(unit)
    cur_start = now - delta
    prev_start = cur_start - delta

    if metric == "left":
        events = EnrollmentEvent.objects.filter(student__in=qs, to_status__in=_LEFT_STATUSES)
        current = events.filter(created_at__gte=cur_start, created_at__lt=now).count()
        previous = events.filter(created_at__gte=prev_start, created_at__lt=cur_start).count()
    else:  # joined
        current = qs.filter(created_at__gte=cur_start, created_at__lt=now).count()
        previous = qs.filter(created_at__gte=prev_start, created_at__lt=cur_start).count()

    delta_n = current - previous
    pct = round((delta_n / previous) * 100, 1) if previous else None
    return {
        "metric": metric,
        "unit": unit,
        "current": current,
        "previous": previous,
        "delta": delta_n,
        "pct_change": pct,
        "current_window": [cur_start.isoformat(), now.isoformat()],
        "previous_window": [prev_start.isoformat(), cur_start.isoformat()],
    }
