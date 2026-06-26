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
from apps.parents.models import Guardian
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


# --- A-3 facet: branch performance ranking --------------------------------------- #
# A transparent owner view: how each branch is doing across attendance, published
# grades, and dropout-risk, blended into one 0-100 score. Model-less / compute-on-read
# like the risk flags. The weights are documented and exposed verbatim via the API.
ACTIVE_STUDENT_STATUSES = (StudentProfile.Status.ENROLLED, StudentProfile.Status.ACTIVE)
BRANCH_WEIGHT_ATTENDANCE = 50  # show-up rate is the strongest health signal
BRANCH_WEIGHT_GRADES = 30
BRANCH_WEIGHT_LOW_RISK = 20  # the inverse of the at-risk share
# Small-cell suppression (k-anonymity): a branch with fewer than this many active
# students has its per-student-revealing metrics (and score) suppressed, so a "branch
# aggregate" can never round-trip one identifiable student's attendance/grade/risk.
MIN_BRANCH_CELL = 3

BRANCH_METRICS: dict[str, dict[str, Any]] = {
    "attendance_rate": {
        "weight": BRANCH_WEIGHT_ATTENDANCE,
        "description": "Share of recent non-excused marks that were present or late.",
    },
    "avg_grade_pct": {
        "weight": BRANCH_WEIGHT_GRADES,
        "description": "Average score across the branch's published exam results.",
    },
    "low_risk": {
        "weight": BRANCH_WEIGHT_LOW_RISK,
        "description": "1 minus the share of active students carrying a dropout-risk flag.",
    },
}


def _branch_score(attendance_rate, avg_grade_pct, at_risk_rate) -> float:
    """Blend the signals into 0-100. Called only for a branch that HAS an academic
    signal (attendance or grades), so a no-data branch is left unranked (None) by the
    caller rather than earning spurious risk credit. A raw score that overshoots (e.g.
    a bonus exam score above max) is clamped to the advertised 0-100 range."""
    att = attendance_rate if attendance_rate is not None else 0.0
    grade = (avg_grade_pct / 100.0) if avg_grade_pct is not None else 0.0
    low_risk = (1.0 - at_risk_rate) if at_risk_rate is not None else 1.0
    raw = att * BRANCH_WEIGHT_ATTENDANCE + grade * BRANCH_WEIGHT_GRADES + low_risk * BRANCH_WEIGHT_LOW_RISK
    return round(max(0.0, min(100.0, raw)), 1)


def branch_ranking(branches, *, now=None, include_finance: bool = True) -> list[dict]:
    """Rank an already-scoped Branch queryset by a transparent performance score over
    each branch's ACTIVE/ENROLLED students. A handful of grouped aggregates (not one
    query per branch) keep it cheap. `include_finance=False` omits the overdue count
    for callers without finance:read.

    Privacy: a branch with fewer than MIN_BRANCH_CELL active students has its metrics
    and score SUPPRESSED (set to None, `suppressed=True`), because at small n a "branch
    aggregate" would be one identifiable student's attendance/grade/risk. A branch with
    no academic signal at all (no attendance, no grades) is left unranked (score None)
    rather than handed a spurious score. Unscored rows sort last."""
    now = now or timezone.now()
    branch_ids = list(branches.values_list("id", flat=True))
    if not branch_ids:
        return []
    window = now - timedelta(days=ATTENDANCE_WINDOW_DAYS)
    students = StudentProfile.objects.filter(branch_id__in=branch_ids, status__in=ACTIVE_STUDENT_STATUSES)

    active_by_branch = {
        row["branch_id"]: row["n"] for row in students.values("branch_id").annotate(n=Count("id"))
    }
    attendance = {
        row["student__branch_id"]: row
        for row in AttendanceRecord.objects.filter(
            student__branch_id__in=branch_ids,
            student__status__in=ACTIVE_STUDENT_STATUSES,
            lesson__starts_at__gte=window,
        )
        .values("student__branch_id")
        .annotate(
            total=Count("id", filter=~Q(status=AttendanceRecord.Status.EXCUSED)),
            attended=Count(
                "id",
                filter=Q(status__in=(AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE)),
            ),
        )
    }
    grades = {
        row["student__branch_id"]: row["avg_pct"]
        for row in ExamResult.objects.filter(
            student__branch_id__in=branch_ids,
            student__status__in=ACTIVE_STUDENT_STATUSES,
            exam__is_published=True,
        )
        .values("student__branch_id")
        .annotate(
            avg_pct=Avg(
                ExpressionWrapper(F("score") * 100.0 / F("exam__max_score"), output_field=FloatField())
            )
        )
    }
    # At-risk count per branch: compute risk once over all active students, map to branch.
    risk_ids = {r["student"] for r in student_risk(students, now=now, include_finance=include_finance)}
    at_risk_by_branch: dict[int, int] = {}
    if risk_ids:
        for _sid, bid in StudentProfile.objects.filter(id__in=risk_ids).values_list("id", "branch_id"):
            at_risk_by_branch[bid] = at_risk_by_branch.get(bid, 0) + 1

    overdue_by_branch: dict[int, int] = {}
    if include_finance:
        overdue_by_branch = {
            row["student__branch_id"]: row["n"]
            for row in Invoice.objects.filter(
                student__branch_id__in=branch_ids,
                student__status__in=ACTIVE_STUDENT_STATUSES,
                status=Invoice.Status.OVERDUE,
            )
            .values("student__branch_id")
            .annotate(n=Count("student_id", distinct=True))
        }

    names = dict(branches.values_list("id", "name"))
    out: list[dict] = []
    for bid in branch_ids:
        active = active_by_branch.get(bid, 0)
        suppressed = 0 < active < MIN_BRANCH_CELL
        if suppressed:
            # Too few students to anonymise — expose only the headcount, nothing that
            # could round-trip an individual student's attendance/grade/risk.
            out.append(
                {
                    "branch": bid,
                    "name": names.get(bid, ""),
                    "active_students": active,
                    "attendance_rate": None,
                    "avg_grade_pct": None,
                    "at_risk": None,
                    "at_risk_rate": None,
                    "overdue_students": None,
                    "suppressed": True,
                    "score": None,
                }
            )
            continue
        att = attendance.get(bid)
        attendance_rate = (att["attended"] / att["total"]) if att and att["total"] else None
        avg_grade = grades.get(bid)
        at_risk = at_risk_by_branch.get(bid, 0)
        at_risk_rate = (at_risk / active) if active else None
        # Only score a branch that has an academic signal; a no-data branch stays
        # unranked rather than collecting a spurious low-risk credit.
        has_signal = attendance_rate is not None or avg_grade is not None
        out.append(
            {
                "branch": bid,
                "name": names.get(bid, ""),
                "active_students": active,
                "attendance_rate": round(attendance_rate, 3) if attendance_rate is not None else None,
                "avg_grade_pct": round(avg_grade, 1) if avg_grade is not None else None,
                "at_risk": at_risk if active else None,
                "at_risk_rate": round(at_risk_rate, 3) if at_risk_rate is not None else None,
                "overdue_students": overdue_by_branch.get(bid, 0) if include_finance else None,
                "suppressed": False,
                "score": _branch_score(attendance_rate, avg_grade, at_risk_rate) if has_signal else None,
            }
        )
    # Highest score first; unscored rows (empty / suppressed / no-signal) sort last.
    out.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0), r["branch"]))
    for rank, row in enumerate(out, start=1):
        row["rank"] = rank
    return out


# --- A-3 facet: family health (retention) ---------------------------------------- #
# A per-FAMILY view for the retention desk: which families have an at-risk or
# overdue child and so are worth a call before they leave. Deliberately NOT
# anonymised — the whole point is to name the family to follow up — so it is gated to
# roles that already see family records (parents:read) and the overdue signal is
# finance-gated. Transparent levels, like the risk rules.
FAMILY_HEALTH_LEVELS: dict[str, str] = {
    "at_risk": "An overdue child, or at least half the children carry a dropout-risk flag.",
    "watch": "At least one child carries a dropout-risk flag.",
    "good": "No dropout-risk flags and nothing overdue.",
}


def _family_health_level(children: int, at_risk: int, overdue: int | None) -> str:
    if (overdue or 0) > 0 or (children and at_risk / children >= 0.5):
        return "at_risk"
    if at_risk > 0:
        return "watch"
    return "good"


def family_health(branches, *, now=None, include_finance: bool = True) -> list[dict]:
    """Score each family (a guardian + the children they guard, within the scoped
    branches) for retention risk. Reuses the dropout-risk rules for the children and,
    when finance is visible, their overdue invoices. Worst-health families first."""
    now = now or timezone.now()
    branch_ids = list(branches.values_list("id", flat=True))
    if not branch_ids:
        return []
    students = StudentProfile.objects.filter(branch_id__in=branch_ids, status__in=ACTIVE_STUDENT_STATUSES)
    student_ids = set(students.values_list("id", flat=True))
    if not student_ids:
        return []

    families: dict[int, dict] = {}
    for g in Guardian.objects.filter(student_id__in=student_ids).select_related("parent__user"):
        parent_user = g.parent.user
        fam = families.setdefault(
            g.parent_id,
            {"name": parent_user.get_full_name() if parent_user else "", "children": set()},
        )
        fam["children"].add(g.student_id)
    if not families:
        return []

    at_risk_ids = {r["student"] for r in student_risk(students, now=now, include_finance=include_finance)}
    overdue_ids: set[int] = set()
    if include_finance:
        overdue_ids = set(
            Invoice.objects.filter(student_id__in=student_ids, status=Invoice.Status.OVERDUE).values_list(
                "student_id", flat=True
            )
        )

    out: list[dict] = []
    for parent_id, fam in families.items():
        children = fam["children"]
        at_risk = len(children & at_risk_ids)
        overdue = len(children & overdue_ids) if include_finance else None
        out.append(
            {
                "family": parent_id,
                "name": fam["name"],
                "children": len(children),
                "at_risk_children": at_risk,
                "overdue_children": overdue,
                "health": _family_health_level(len(children), at_risk, overdue),
            }
        )
    order = {"at_risk": 0, "watch": 1, "good": 2}
    out.sort(key=lambda r: (order.get(r["health"], 9), -r["at_risk_children"], r["family"]))
    return out


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
