"""Backend API contract: every response is JSON — errors use the
``{"error": {"code", "detail"}}`` envelope, and there is no HTML browsable-API UI.
Mobile/web clients must never receive an HTML page (a template or a DEBUG error page)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_unmatched_url_is_json_404_not_html(tenant_a, client_for):
    resp = client_for(tenant_a).get("/api/v1/definitely-not-a-real-endpoint/")
    assert resp.status_code == 404
    assert resp["Content-Type"].startswith("application/json")
    assert resp.json()["error"]["code"] == "not_found"


def test_unauthenticated_request_is_json_401(tenant_a, client_for):
    resp = client_for(tenant_a).get("/api/v1/users/me/")
    assert resp.status_code == 401
    assert resp["Content-Type"].startswith("application/json")
    assert "error" in resp.json()


def test_method_not_allowed_is_json(tenant_a, user_in, as_user):
    # DELETE on a collection that doesn't allow it -> JSON 405, never an HTML page.
    client = as_user(tenant_a, user_in(tenant_a, roles=["teacher"]))
    resp = client.delete("/api/v1/users/me/")
    assert resp.status_code in (403, 405)
    assert resp["Content-Type"].startswith("application/json")


def test_no_browsable_api_html_ui(tenant_a, user_in, as_user):
    """Even when a browser asks for HTML (Accept: text/html), the API answers JSON —
    the DRF browsable-API HTML interface is disabled (this is a backend API)."""
    client = as_user(tenant_a, user_in(tenant_a, roles=["teacher"]))
    resp = client.get("/api/v1/users/me/", HTTP_ACCEPT="text/html")
    assert "text/html" not in resp["Content-Type"]
