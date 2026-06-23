"""Teacher read selectors."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.teachers.models import TeacherProfile


def list_teachers() -> QuerySet[TeacherProfile]:
    return TeacherProfile.objects.select_related("user", "branch", "department")


def teacher_profile_for(user) -> TeacherProfile | None:
    return TeacherProfile.objects.filter(user=user).first()


def teacher_dashboard(*, teacher: TeacherProfile, user, roles) -> dict:
    """A single read over the teacher's groups, schedule (with lesson types), exams,
    expected graduations, and outstanding rule acknowledgments (F3-2)."""
    from apps.academics.models import Exam
    from apps.cohorts.models import Cohort, CohortMembership
    from apps.compliance import selectors as compliance_selectors
    from apps.schedule.models import Lesson

    now = timezone.now()
    today = now.date()

    cohorts = Cohort.objects.filter(
        Q(primary_teacher=teacher) | Q(co_teachers__teacher=teacher)
    ).distinct()
    cohort_ids = list(cohorts.values_list("id", flat=True))

    level_groups: dict[str, int] = {}
    for cohort in cohorts:
        key = cohort.level or "—"
        level_groups[key] = level_groups.get(key, 0) + 1

    students_count = (
        CohortMembership.objects.filter(cohort_id__in=cohort_ids, end_date__isnull=True)
        .values("student_id")
        .distinct()
        .count()
    )

    next_lessons = [
        {
            "id": lesson.id,
            "title": lesson.title,
            "cohort": lesson.cohort.name,
            "starts_at": lesson.starts_at,
            "ends_at": lesson.ends_at,
            "lesson_type": lesson.lesson_type.name if lesson.lesson_type else None,
        }
        for lesson in Lesson.objects.filter(
            teacher=teacher, starts_at__gte=now, status=Lesson.Status.SCHEDULED
        )
        .select_related("cohort", "lesson_type")
        .order_by("starts_at")[:5]
    ]

    upcoming_exams = [
        {"id": exam.id, "title": exam.title, "cohort": exam.cohort.name, "exam_date": exam.exam_date}
        for exam in Exam.objects.filter(cohort_id__in=cohort_ids, exam_date__gte=today)
        .select_related("cohort")
        .order_by("exam_date")[:5]
    ]

    graduations = [
        {"cohort": cohort.name, "end_date": cohort.end_date}
        for cohort in cohorts.filter(end_date__gte=today).order_by("end_date")[:10]
    ]

    return {
        "groups_count": len(cohort_ids),
        "students_count": students_count,
        "level_groups": level_groups,
        "next_lessons": next_lessons,
        "upcoming_exams": upcoming_exams,
        "expected_graduations": graduations,
        "pending_rule_acknowledgments": len(compliance_selectors.pending_rules(user, roles)),
    }
