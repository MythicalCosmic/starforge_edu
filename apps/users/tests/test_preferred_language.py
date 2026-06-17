"""PATCH /api/v1/users/me/ {preferred_language} self-service (D4-LF-3).

Lane F verifies the profile write path that drives the localized notification
template variant. The field already exists (Day-1) and is writable on
UserSerializer; this proves the endpoint round-trips it and stays self-scoped.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_patch_me_updates_preferred_language(tenant_a, user_in, as_user):
    user = user_in(tenant_a, preferred_language="uz")
    client = as_user(tenant_a, user)

    resp = client.patch("/api/v1/users/me/", {"preferred_language": "ru"}, format="json")

    assert resp.status_code == 200, resp.content
    assert resp.json()["preferred_language"] == "ru"
    user.refresh_from_db()
    assert user.preferred_language == "ru"


def test_patch_me_rejects_invalid_language(tenant_a, user_in, as_user):
    user = user_in(tenant_a, preferred_language="uz")
    client = as_user(tenant_a, user)

    resp = client.patch("/api/v1/users/me/", {"preferred_language": "xx"}, format="json")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_patch_me_ignores_read_only_fields(tenant_a, user_in, as_user):
    """username / is_staff are read-only — a PATCH attempting them is a no-op on them."""
    user = user_in(tenant_a, preferred_language="uz")
    original_username = user.username
    client = as_user(tenant_a, user)

    resp = client.patch(
        "/api/v1/users/me/",
        {"preferred_language": "en", "username": "hacker", "is_staff": True},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    user.refresh_from_db()
    assert user.preferred_language == "en"
    assert user.username == original_username
    assert user.is_staff is False


def test_patch_me_requires_auth(tenant_a, client_for):
    client = client_for(tenant_a)
    resp = client.patch("/api/v1/users/me/", {"preferred_language": "ru"}, format="json")
    assert resp.status_code == 401
