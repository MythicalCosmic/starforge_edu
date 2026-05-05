"""Celery app entrypoint.

Uses tenant-schemas-celery so every task body runs under the correct
tenant schema. The `schema_name` kwarg is passed automatically by the
client wrapper; calling `task.delay(..., _schema_name="acme")` activates
the schema for the task's lifetime.
"""

import os

from tenant_schemas_celery.app import CeleryApp

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = CeleryApp("starforge")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["celery_tasks"])


@app.task(bind=True)
def debug_task(self):  # pragma: no cover
    print(f"Request: {self.request!r}")
