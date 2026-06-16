"""Assignment beat tasks (D2-D-7). Fan-out per tenant; the body lives in
apps.assignments.services.emit_due_soon_reminders. Emit-only — nothing here
imports an sms/email/push/anthropic adapter (D3-C wires dispatch)."""

from __future__ import annotations

from config.celery import app


def _active_schemas():
    from apps.tenancy.models import Center

    return list(Center.objects.filter(is_active=True).values_list("schema_name", flat=True))


@app.task
def send_due_soon_reminders() -> int:
    """Public dispatcher: fan out the due-soon sweep to each active Center."""
    schemas = _active_schemas()
    for schema in schemas:
        send_due_soon_reminders_for_schema.delay(_schema_name=schema)
    return len(schemas)


@app.task
def send_due_soon_reminders_for_schema() -> int:
    from apps.assignments.services import emit_due_soon_reminders

    return emit_due_soon_reminders()
