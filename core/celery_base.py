"""Project Celery task base.

tenant-schemas-celery's ``TenantTask`` activates the tenant schema from the
task **headers** (``headers["_schema_name"]``), set by its ``apply``/``send_task``
overrides + the ``task_prerun`` signal. Throughout the codebase, however,
fan-out dispatchers call ``some_task.delay(..., _schema_name=center.schema_name)``
— which passes ``_schema_name`` as a task **kwarg**, so it leaks into the task
signature (``TypeError`` in eager tests, and the schema is never activated in
production). This base lifts a ``_schema_name`` kwarg into the headers, making
the ergonomic ``.delay(_schema_name=...)`` call style correct everywhere.
"""

from __future__ import annotations

from typing import Any

from tenant_schemas_celery.task import TenantTask


class SchemaHeaderTask(TenantTask):
    abstract = True

    def apply_async(self, args=None, kwargs=None, **options) -> Any:
        if kwargs and "_schema_name" in kwargs:
            kwargs = dict(kwargs)
            schema = kwargs.pop("_schema_name")
            if schema:
                headers = dict(options.get("headers") or {})
                headers.setdefault("_schema_name", schema)
                options["headers"] = headers
        return super().apply_async(args=args, kwargs=kwargs, **options)
