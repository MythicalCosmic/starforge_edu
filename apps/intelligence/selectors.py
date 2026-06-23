"""A-3 intelligence pipeline — student dropout-risk flags from TRANSPARENT RULES.

Dropout is the #1 revenue leak, so the first slice of the pipeline surfaces
at-risk students. There is deliberately NO black-box model: every flag is a
documented rule over data the center already has (attendance, published grades,
overdue invoices), computed on read so it is always current and fully explainable.
`RULES` is exposed verbatim through the API so a center sees exactly how flags fire.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Q, QuerySet
from django.utils import timezone

from apps.academics.models import ExamResult
from apps.attendance.models import AttendanceRecord
from apps.finance.models import Invoice
from apps.students.models import StudentProfile

# --- transparent, documented thresholds (will move to CenterSettings later) ----- #
ATTENDANCE_WINDOW_DAYS = 30
MIN_LESSONS_FOR_ATTENDANCE_FLAG = 4
ABSENCE_RATE_THRESHOLD = 0.30  # absent >= 30% of recent lessons
LOW_GRADE_PCT_THRESHOLD = 50.0  # average published score < 50%

# Each rule's weight; the sum is the risk score, which maps to a level below.
RULES: dict[str, dict[str, Any]] = {
    "low_attendance": {
        "weight": 3,
        "description": (
            f"Absent in {int(ABSENCE_RATE_THRESHOLD * 100)}%+ of the last "
            f"{ATTENDANCE_WINDOW_DAYS} days' lessons "
            f"(min {MIN_LESSONS_FOR_ATTENDANCE_FLAG} lessons)."
        ),
    },
    "low_grades": {
        "weight": 2,
        "description": f"Average published exam score below {int(LOW_GRADE_PCT_THRESHOLD)}%.",
    },
    "overdue_payment": {"weight": 2, "description": "Has at least one overdue invoice."},
}


def _level(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"  # only reached for an at-risk student (score >= 1)


def student_risk(students: QuerySet[StudentProfile], *, now=None, include_finance: bool = True) -> list[dict]:
    """Compute risk flags for an already-scoped student queryset. Returns ONLY the
    at-risk students (>=1 flag), highest score first. A few aggregate queries (not
    one-per-student) keep it cheap. `include_finance=False` omits the overdue-payment
    flag for callers who may not see finance."""
    now = now or timezone.now()
    ids = list(students.values_list("id", flat=True))
    if not ids:
        return []

    window = now - timedelta(days=ATTENDANCE_WINDOW_DAYS)
    attendance = {
        row["student_id"]: row
        # Window keys on the LESSON's date, not the row-write time, so a late
        # backfill/correction can't inject old lessons into "the last 30 days".
        # `total` excludes EXCUSED so an excused absence neither hurts nor dilutes.
        for row in AttendanceRecord.objects.filter(student_id__in=ids, lesson__starts_at__gte=window)
        .values("student_id")
        .annotate(
            total=Count("id", filter=~Q(status=AttendanceRecord.Status.EXCUSED)),
            absent=Count("id", filter=Q(status=AttendanceRecord.Status.ABSENT)),
        )
    }
    grades = {
        row["student_id"]: row["avg_pct"]
        for row in ExamResult.objects.filter(student_id__in=ids, exam__is_published=True)
        .values("student_id")
        .annotate(
            avg_pct=Avg(
                ExpressionWrapper(F("score") * 100.0 / F("exam__max_score"), output_field=FloatField())
            )
        )
    }
    # The overdue (financial) signal is only computed for callers who may see finance
    # — never leak a student's tuition-arrears status to a role without finance:read.
    overdue: set[int] = set()
    if include_finance:
        overdue = set(
            Invoice.objects.filter(student_id__in=ids, status=Invoice.Status.OVERDUE).values_list(
                "student_id", flat=True
            )
        )

    flagged: list[tuple[int, list[dict]]] = []
    for sid in ids:
        flags = _flags_for(attendance.get(sid), grades.get(sid), sid in overdue)
        if flags:
            flagged.append((sid, flags))

    # Load full rows (name/cohort) only for the flagged subset, not every scoped student.
    by_id = {
        s.id: s
        for s in StudentProfile.objects.filter(id__in=[sid for sid, _ in flagged]).select_related("user")
    }
    out: list[dict] = []
    for sid, flags in flagged:
        score = sum(RULES[f["code"]]["weight"] for f in flags)
        student = by_id[sid]
        out.append(
            {
                "student": sid,
                "name": student.user.get_full_name() if student.user else "",
                "cohort": student.current_cohort_id,
                "score": score,
                "level": _level(score),
                "flags": flags,
            }
        )
    out.sort(key=lambda r: (-r["score"], r["student"]))
    return out


def _flags_for(att, avg_pct, is_overdue) -> list[dict]:
    flags: list[dict] = []
    if (
        att
        and att["total"] >= MIN_LESSONS_FOR_ATTENDANCE_FLAG
        and (att["absent"] / att["total"]) >= ABSENCE_RATE_THRESHOLD
    ):
        flags.append(
            {"code": "low_attendance", "reason": f"Absent {att['absent']} of last {att['total']} lessons."}
        )
    if avg_pct is not None and avg_pct < LOW_GRADE_PCT_THRESHOLD:
        flags.append({"code": "low_grades", "reason": f"Recent average {round(avg_pct, 1)}%."})
    if is_overdue:
        flags.append({"code": "overdue_payment", "reason": "Has an overdue invoice."})
    return flags


def student_risk_detail(student: StudentProfile, *, now=None, include_finance: bool = True) -> dict:
    """Full risk picture for ONE student (transparency view) — the flags it fires
    plus a 'none' result when it's healthy, so a center can always see the reasoning."""
    rows = student_risk(
        StudentProfile.objects.filter(pk=student.pk), now=now, include_finance=include_finance
    )
    if rows:
        return rows[0]
    return {
        "student": student.pk,
        "name": student.user.get_full_name() if student.user else "",
        "cohort": student.current_cohort_id,
        "score": 0,
        "level": "none",
        "flags": [],
    }
