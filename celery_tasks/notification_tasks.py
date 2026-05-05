"""Celery tasks for notification dispatch.

Tasks are auto-registered with tenant-schemas-celery; pass `_schema_name`
when scheduling from a context that already knows the tenant.
"""

from __future__ import annotations

from config.celery import app


@app.task(bind=True, max_retries=5, default_retry_delay=60)
def dispatch_notification(self, notification_id: int) -> None:
    """Resolve preferences and fan out to channels (sms/email/push/in-app)."""

    # TODO(v1): apps.notifications.services.dispatch(notification_id)
    return None
