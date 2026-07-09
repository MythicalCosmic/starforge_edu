"""Fault isolation (core.availability): every app can be turned off, one app down never
falls the whole API, dependency-aware graceful degradation with warnings, controllable."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db


def _disable(tenant, apps):
    from core.availability import set_tenant_disabled_apps

    with schema_context(tenant.schema_name):
        set_tenant_disabled_apps(set(apps))


# --- resolve_status (pure logic) ------------------------------------------
def test_resolve_status_transitive(tenant_a):
    from core.availability import (
        STATUS_DEGRADED,
        STATUS_DISABLED,
        STATUS_UNAVAILABLE,
        STATUS_UP,
        resolve_status,
    )

    cache.clear()
    with schema_context(tenant_a.schema_name):
        assert resolve_status("finance")[0] == STATUS_UP  # nothing disabled
    _disable(tenant_a, {"approvals"})
    with schema_context(tenant_a.schema_name):
        assert resolve_status("approvals")[0] == STATUS_DISABLED
        assert resolve_status("finance")[0] == STATUS_UNAVAILABLE  # hard dep down
        assert resolve_status("cohorts")[0] == STATUS_UP  # unrelated app unaffected
    _disable(tenant_a, {"notifications"})
    with schema_context(tenant_a.schema_name):
        status, warnings = resolve_status("attendance")  # soft dep down
        assert status == STATUS_DEGRADED
        assert any("notifications" in w for w in warnings)


# --- HTTP integration -----------------------------------------------------
def test_disabled_app_503s_and_others_keep_working(tenant_a, as_role):
    cache.clear()
    director, _ = as_role(Role.DIRECTOR)
    _disable(tenant_a, {"placement"})
    down = director.get("/api/v1/placement/tests/")
    assert down.status_code == 503
    body = down.json()
    assert body["success"] is False
    assert body["code"] == "service_unavailable"
    # a different app is completely unaffected — the project did NOT fall
    assert director.get("/api/v1/cohorts/").status_code == 200


def test_hard_dependency_down_makes_dependent_app_unavailable(tenant_a, as_role):
    cache.clear()
    director, _ = as_role(Role.DIRECTOR)
    _disable(tenant_a, {"approvals"})  # finance hard-depends on the A-1 approvals engine
    assert director.get("/api/v1/finance/invoices/").status_code == 503
    assert director.get("/api/v1/cohorts/").status_code == 200  # unrelated app fine


def test_soft_dependency_down_degrades_with_warnings(tenant_a, as_role):
    cache.clear()
    director, _ = as_role(Role.DIRECTOR)
    _disable(tenant_a, {"notifications"})  # attendance soft-depends on notifications
    r = director.get("/api/v1/attendance/records/")
    assert r.status_code == 200  # still works
    body = r.json()
    assert "warnings" in body
    assert any("notifications" in w for w in body["warnings"])


def test_control_endpoint_lists_and_toggles(tenant_a, as_role):
    cache.clear()
    director, _ = as_role(Role.DIRECTOR)
    listing = director.get("/api/v1/org/system/apps/")
    assert listing.status_code == 200
    apps = {a["app"]: a["status"] for a in listing.json()["data"]["apps"]}
    assert apps.get("finance") == "up"

    patched = director.patch("/api/v1/org/system/apps/", {"disabled": ["placement"]}, format="json")
    assert patched.status_code == 200
    assert "placement" in patched.json()["data"]["disabled"]
    # the toggle took effect immediately (no restart)
    assert director.get("/api/v1/placement/tests/").status_code == 503
    # ...and re-enabling brings it back
    director.patch("/api/v1/org/system/apps/", {"disabled": []}, format="json")
    assert director.get("/api/v1/placement/tests/").status_code == 200


def test_control_endpoint_rejects_a_bad_body(tenant_a, as_role):
    cache.clear()
    director, _ = as_role(Role.DIRECTOR)
    r = director.patch("/api/v1/org/system/apps/", {"disabled": "placement"}, format="json")
    assert r.status_code == 400
