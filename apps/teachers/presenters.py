"""Teacher presenters — plain dict mappers (replace TeacherReadSerializer)."""

from __future__ import annotations

from typing import Any

from apps.teachers.models import TeacherProfile
from apps.users.presenters import user_brief


def teacher_to_dict(teacher: TeacherProfile) -> dict[str, Any]:
    return {
        "id": teacher.id,
        "user": user_brief(teacher.user),
        "branch": teacher.branch_id,
        "department": teacher.department_id,
        "hire_date": teacher.hire_date.isoformat() if teacher.hire_date else None,
        "subjects": teacher.subjects,
        "qualifications": teacher.qualifications,
        "salary_type": teacher.salary_type,
        "rate": str(teacher.rate) if teacher.rate is not None else None,
        "is_substitute": teacher.is_substitute,
        "created_at": teacher.created_at.isoformat(),
    }
