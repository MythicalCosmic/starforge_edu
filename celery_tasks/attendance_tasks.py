"""Attendance beat tasks (D2-B-7). Fan-out per tenant; the body lives in
apps.attendance.services.auto_mark_absent. Emit-only — nothing here imports an
sms/email/push adapter (D3-C wires guardian dispatch off `student_marked_absent`).
"""

from __future__ import annotations

from config.celery import app


def _active_schemas():
    from apps.tenancy.models import Center

    return list(Center.objects.filter(is_active=True).values_list("schema_name", flat=True))


@app.task
def mark_absent_after_lesson() -> int:
    """Public dispatcher: fan out the auto-absent sweep to each active Center."""
    schemas = _active_schemas()
    for schema in schemas:
        mark_absent_after_lesson_for_schema.delay(_schema_name=schema)
    return len(schemas)


@app.task
def mark_absent_after_lesson_for_schema() -> int:
    from apps.attendance.services import auto_mark_absent

    return auto_mark_absent()
