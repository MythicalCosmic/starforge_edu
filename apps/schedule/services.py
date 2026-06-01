"""Schedule services: conflict detection + recurring lesson generation.

A lesson conflicts with another non-cancelled lesson when their time ranges
overlap AND they share a room, a teacher, or a cohort. Overlap is the standard
half-open test: a.start < b.end AND a.end > b.start (touching edges don't clash).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import Holiday, Lesson


def find_conflicts(
    *,
    start: datetime,
    end: datetime,
    room=None,
    teacher=None,
    cohort=None,
    exclude_id: int | None = None,
) -> QuerySet[Lesson]:
    """Return non-cancelled lessons that overlap [start, end) and share a resource."""
    target = Q()
    if room is not None:
        target |= Q(room=room)
    if teacher is not None:
        target |= Q(teacher=teacher)
    if cohort is not None:
        target |= Q(cohort=cohort)
    if not target:  # nothing to collide on
        return Lesson.objects.none()

    qs = (
        Lesson.objects.exclude(status=Lesson.Status.CANCELLED)
        .filter(start__lt=end, end__gt=start)
        .filter(target)
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs


def describe_conflicts(lesson_qs: QuerySet[Lesson], *, room=None, teacher=None, cohort=None) -> list[str]:
    """Human-readable reasons for each conflicting lesson (which resource clashed)."""
    out = []
    for lsn in lesson_qs:
        reasons = []
        if room is not None and lsn.room_id == getattr(room, "pk", room):
            reasons.append("room")
        if teacher is not None and lsn.teacher_id == getattr(teacher, "pk", teacher):
            reasons.append("teacher")
        if cohort is not None and lsn.cohort_id == getattr(cohort, "pk", cohort):
            reasons.append("cohort")
        out.append(f"lesson #{lsn.pk} ({', '.join(reasons) or 'overlap'}) at {lsn.start:%Y-%m-%d %H:%M}")
    return out


def create_recurring(
    *,
    cohort,
    start_time: time,
    end_time: time,
    weekdays,
    start_date: date,
    end_date: date,
    room=None,
    teacher=None,
    skip_holidays: bool = True,
) -> tuple[list[Lesson], list[dict]]:
    """Materialize weekly lessons across a date range.

    weekdays: ints, Mon=0 .. Sun=6. Days that are holidays or that would create a
    conflict are skipped (recorded in the returned `skipped` list with a reason).
    All occurrences share one series_id so a single one can later be cancelled/moved.
    """
    weekdays = set(weekdays)
    holidays: set[date] = set()
    if skip_holidays:
        holidays = set(
            Holiday.objects.filter(
                Q(branch=cohort.branch) | Q(branch__isnull=True),
                date__range=(start_date, end_date),
            ).values_list("date", flat=True)
        )

    series_id = uuid.uuid4()
    created: list[Lesson] = []
    skipped: list[dict] = []

    day = start_date
    while day <= end_date:
        if day.weekday() in weekdays and day not in holidays:
            start = timezone.make_aware(datetime.combine(day, start_time))
            end = timezone.make_aware(datetime.combine(day, end_time))
            conflicts = find_conflicts(start=start, end=end, room=room, teacher=teacher, cohort=cohort)
            if conflicts.exists():
                skipped.append({"date": day.isoformat(), "reason": "conflict"})
            else:
                created.append(
                    Lesson.objects.create(
                        cohort=cohort,
                        room=room,
                        teacher=teacher,
                        start=start,
                        end=end,
                        series_id=series_id,
                    )
                )
        day += timedelta(days=1)
    return created, skipped
