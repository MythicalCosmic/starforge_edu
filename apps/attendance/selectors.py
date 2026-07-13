"""Attendance read selectors: role-scoped record queries, term summary, and the
single-query cohort dashboard."""

from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from apps.attendance.models import AttendanceRecord
from apps.cohorts.models import Cohort
from core.permissions import Role
from core.scoping import role_membership_scope_q


def _base() -> QuerySet[AttendanceRecord]:
    # lesson__cohort (the group) + lesson__teacher__user (the teacher) are surfaced in
    # the presenter, so join them here — no extra query per row.
    return AttendanceRecord.objects.select_related("student__user", "lesson__cohort", "lesson__teacher__user")


def scoped_records(*, user, roles: set[str] | None = None) -> QuerySet[AttendanceRecord]:
    """Records visible through management membership, teaching, family, or self scope."""
    qs = _base()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs

    visible = Q(pk__in=[])
    if Role.HEAD_OF_DEPT in roles:
        visible |= role_membership_scope_q(
            user=user,
            roles={Role.HEAD_OF_DEPT},
            branch_field="lesson__cohort__branch_id",
            department_field="lesson__cohort__department_id",
        )
    if Role.TEACHER in roles:
        visible |= Q(lesson__teacher__user=user)
    if Role.PARENT in roles:
        visible |= Q(student__guardians__parent__user=user)
    if Role.STUDENT in roles:
        visible |= Q(student__user=user)
    return qs.filter(visible).distinct()


def scoped_dashboard_cohorts(*, user, roles: set[str] | None = None) -> QuerySet[Cohort]:
    """Cohorts whose whole-class attendance dashboard ``user`` may inspect."""
    qs = Cohort.objects.all()
    if user.is_superuser:
        return qs
    if roles is None:
        roles = {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}
    if Role.DIRECTOR in roles:
        return qs

    visible = Q(pk__in=[])
    if Role.HEAD_OF_DEPT in roles:
        visible |= role_membership_scope_q(
            user=user,
            roles={Role.HEAD_OF_DEPT},
            branch_field="branch_id",
            department_field="department_id",
        )
    if Role.TEACHER in roles:
        visible |= (
            Q(primary_teacher__user=user)
            | Q(co_teachers__teacher__user=user)
            | Q(lessons__teacher__user=user)
        )
    return qs.filter(visible).distinct()


def term_summary(*, base_qs: QuerySet[AttendanceRecord], student_id: int, term_id: int) -> dict:
    """Per-student per-term counts + `percent_present` (present / total * 100).

    `base_qs` is a scoped queryset, so a student/parent asking for someone else's
    summary gets all-zeros rather than a leak. Single aggregate query."""
    counts = base_qs.filter(student_id=student_id, lesson__term_id=term_id).aggregate(
        present=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
        absent=Count("id", filter=Q(status=AttendanceRecord.Status.ABSENT)),
        late=Count("id", filter=Q(status=AttendanceRecord.Status.LATE)),
        excused=Count("id", filter=Q(status=AttendanceRecord.Status.EXCUSED)),
        total=Count("id"),
    )
    total = counts.pop("total")
    counts["percent_present"] = round(100 * counts["present"] / total, 1) if total else 0.0
    return counts


def cohort_dashboard(*, cohort_id: int, date_from=None, date_to=None) -> dict:
    """Per-student present/absent/late/excused counts + rate for one cohort, plus
    a cohort-wide rate. ONE aggregate query (≤5 for the whole request, DoD)."""
    qs = AttendanceRecord.objects.filter(lesson__cohort_id=cohort_id)
    if date_from is not None:
        qs = qs.filter(lesson__starts_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(lesson__starts_at__lte=date_to)

    rows = list(
        qs.values(
            "student_id",
            "student__student_id",
            "student__user__first_name",
            "student__user__last_name",
        )
        .annotate(
            present=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
            absent=Count("id", filter=Q(status=AttendanceRecord.Status.ABSENT)),
            late=Count("id", filter=Q(status=AttendanceRecord.Status.LATE)),
            excused=Count("id", filter=Q(status=AttendanceRecord.Status.EXCUSED)),
            total=Count("id"),
        )
        .order_by("student__user__last_name", "student__user__first_name")
    )

    students = []
    cohort_present = cohort_total = 0
    for row in rows:
        total = row["total"]
        cohort_present += row["present"]
        cohort_total += total
        name = f"{row['student__user__first_name']} {row['student__user__last_name']}".strip()
        students.append(
            {
                "student": row["student_id"],
                "student_code": row["student__student_id"],
                "name": name,
                "present": row["present"],
                "absent": row["absent"],
                "late": row["late"],
                "excused": row["excused"],
                "total": total,
                "percent_present": round(100 * row["present"] / total, 1) if total else 0.0,
            }
        )
    cohort_rate = round(100 * cohort_present / cohort_total, 1) if cohort_total else 0.0
    return {"cohort": cohort_id, "rate": cohort_rate, "students": students}
