"""Attendance response presenters (formerly the DRF serializers' output shape)."""

from __future__ import annotations

from apps.attendance.models import AttendanceRecord


def record_to_dict(record: AttendanceRecord) -> dict:
    """Flat record shape with denormalized `student_name`/`lesson_title`, resolved
    from the selector's select_related("student__user", "lesson") — no extra query
    per row."""
    return {
        "id": record.id,
        "student": record.student_id,
        "student_name": record.student.user.get_full_name(),
        "lesson": record.lesson_id,
        "lesson_title": record.lesson.title,
        "status": record.status,
        "arrived_at": record.arrived_at.isoformat() if record.arrived_at else None,
        "note": record.note,
        "marked_by": record.marked_by_id,
        "marked_at": record.marked_at.isoformat() if record.marked_at else None,
        "auto_marked": record.auto_marked,
        "created_at": record.created_at.isoformat(),
    }
