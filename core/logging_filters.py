"""Logging filter that injects the active django-tenants schema name."""

import logging

from django.db import connection


class TenantSchemaFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.schema = connection.schema_name  # type: ignore[attr-defined]
        except Exception:
            record.schema = "-"
        return True
