"""Feature 2 — student list page: profile fields, block/unblock, filters,
stats, comparison. Built against agents/FEATURE_BACKLOG.md (F2-*)."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from apps.org.tests.factories import BranchFactory
from core.permissions import Role

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# F2-1 — profile fields (location, previous_school) + is_blocked flag
# --------------------------------------------------------------------------- #
def test_create_and_read_location_and_previous_school(tenant_a, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory.create()
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    resp = client.post(
        "/api/v1/students/",
        {
            "phone": "+998905557001",
            "branch": branch.pk,
            "location": "Tashkent, Yunusabad",
            "previous_school": "School #110",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    sid = resp.json()["id"]
    body = client.get(f"/api/v1/students/{sid}/").json()
    assert body["location"] == "Tashkent, Yunusabad"
    assert body["previous_school"] == "School #110"
    assert body["is_blocked"] is False
    assert body["blocked_at"] is None
