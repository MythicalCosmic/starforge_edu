"""Schedule beat tasks (D2-A-7). Fan-out per tenant; bodies live in
apps.schedule.services. Emit-only — nothing here imports an sms/email/push
adapter (D3-C wires dispatch)."""

from __future__ import annotations

from config.celery import app


def _active_schemas():
    from apps.tenancy.models import Center

    return list(Center.objects.filter(is_active=True).values_list("schema_name", flat=True))


@app.task
def send_lesson_reminders() -> int:
    """Public dispatcher: fan out a per-tenant reminder task to each active Center."""
    schemas = _active_schemas()
    for schema in schemas:
        send_lesson_reminders_for_schema.delay(_schema_name=schema)
    return len(schemas)


@app.task
def send_lesson_reminders_for_schema() -> int:
    from apps.schedule.services import emit_due_reminders

    return emit_due_reminders()


@app.task
def archive_completed_terms() -> int:
    """Public dispatcher: fan out term archival to each active Center."""
    schemas = _active_schemas()
    for schema in schemas:
        archive_completed_terms_for_schema.delay(_schema_name=schema)
    return len(schemas)


@app.task
def archive_completed_terms_for_schema() -> int:
    from apps.schedule.services import archive_ended_term_lessons

    return archive_ended_term_lessons()
