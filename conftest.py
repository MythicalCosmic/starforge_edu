"""Pytest bootstrap for a django-tenants project.

pytest-django's default ``django_db_setup`` runs the stock ``migrate`` command.
Under django-tenants that breaks: the tenant router lets shared apps (e.g.
``django.contrib.admin``) build their tables in the public schema, but their
FKs point at ``AUTH_USER_MODEL`` (``users.User``), which is a *tenant-only*
app — so ``django_admin_log`` cannot be created in public.

We instead create the test database ourselves and migrate the shared schema via
``migrate_schemas --shared`` (the same command the README documents). Per-tenant
schemas are then created on demand by ``TenantTestCase``/``FastTenantTestCase``.
"""

from __future__ import annotations

import pytest
from django.conf import settings


def _recreate_test_database() -> str:
    """Drop and recreate the test database; return its name."""
    import psycopg

    db = settings.DATABASES["default"]
    test_name = (db.get("TEST") or {}).get("NAME") or f"test_{db['NAME']}"
    conn = psycopg.connect(
        host=db["HOST"] or "localhost",
        port=db["PORT"] or 5432,
        user=db["USER"],
        password=db["PASSWORD"],
        dbname="postgres",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{test_name}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{test_name}"')
    finally:
        conn.close()
    return test_name


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    from django.core.management import call_command
    from django.db import connection

    test_name = _recreate_test_database()
    settings.DATABASES["default"]["NAME"] = test_name
    connection.close()
    connection.settings_dict["NAME"] = test_name

    with django_db_blocker.unblock():
        call_command("migrate_schemas", shared=True, interactive=False, verbosity=0)

    return
