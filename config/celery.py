"""Celery app entrypoint.

Uses tenant-schemas-celery so every task body runs under the correct
tenant schema. The `schema_name` kwarg is passed automatically by the
client wrapper; calling `task.delay(..., _schema_name="acme")` activates
the schema for the task's lifetime.
"""

import os

from tenant_schemas_celery.app import CeleryApp

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# SchemaHeaderTask lets `.delay(..., _schema_name="acme")` work correctly: it
# lifts the kwarg into task headers, where tenant-schemas-celery reads it to
# activate the schema (otherwise it leaks into the task signature).
app = CeleryApp("starforge", task_cls="core.celery_base:SchemaHeaderTask")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["celery_tasks"])


@app.task(bind=True)
def debug_task(self):  # pragma: no cover
    print(f"Request: {self.request!r}")
