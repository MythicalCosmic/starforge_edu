"""Cohort presenters — plain dict mappers (replace the DRF ModelSerializers)."""

from __future__ import annotations

from typing import Any

from apps.cohorts.models import Cohort, CohortMembership, CohortTeacher


def cohort_teacher_to_dict(ct: CohortTeacher) -> dict[str, Any]:
    return {"id": ct.id, "teacher": ct.teacher_id, "role": ct.role}


def cohort_to_dict(cohort: Cohort) -> dict[str, Any]:
    return {
        "id": cohort.id,
        "name": cohort.name,
        "branch": cohort.branch_id,
        "department": cohort.department_id,
        "level": cohort.level,
        "start_date": cohort.start_date.isoformat(),
        "end_date": cohort.end_date.isoformat(),
        "capacity": cohort.capacity,
        "primary_teacher": cohort.primary_teacher_id,
        "default_room": cohort.default_room_id,
        "is_archived": cohort.is_archived,
        "co_teachers": [cohort_teacher_to_dict(ct) for ct in cohort.co_teachers.all()],
        "created_at": cohort.created_at.isoformat(),
    }


def membership_to_dict(m: CohortMembership) -> dict[str, Any]:
    return {
        "id": m.id,
        "cohort": m.cohort_id,
        "student": m.student_id,
        "start_date": m.start_date.isoformat(),
        "end_date": m.end_date.isoformat() if m.end_date else None,
        "moved_reason": m.moved_reason,
    }
