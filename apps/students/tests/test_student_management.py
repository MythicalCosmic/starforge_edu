"""Feature 2 — student list page: profile fields, block/unblock, filters,
stats, comparison. Built against agents/FEATURE_BACKLOG.md (F2-*)."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from apps.org.tests.factories import BranchFactory
from apps.students.services import create_student
from core.permissions import Role

pytestmark = pytest.mark.django_db


def _branch_and_client(tenant, user_in, as_user, role=Role.REGISTRAR):
    with schema_context(tenant.schema_name):
        branch = BranchFactory.create()
    client = as_user(tenant, user_in(tenant, roles=[role], branch=branch))
    return branch, client


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


# --------------------------------------------------------------------------- #
# F2-2 — block / unblock
# --------------------------------------------------------------------------- #
def test_block_then_unblock_student(tenant_a, user_in, as_user):
    branch, client = _branch_and_client(tenant_a, user_in, as_user)
    with schema_context(tenant_a.schema_name):
        student = create_student(branch=branch, phone="+998905557010")

    resp = client.post(
        f"/api/v1/students/{student.id}/block/", {"reason": "unpaid balance"}, format="json"
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["is_blocked"] is True
    assert body["blocked_at"] is not None
    assert body["block_reason"] == "unpaid balance"

    resp = client.post(f"/api/v1/students/{student.id}/unblock/", {}, format="json")
    assert resp.status_code == 200
    assert resp.json()["is_blocked"] is False


def test_block_requires_write_role(tenant_a, user_in, as_user):
    branch, _ = _branch_and_client(tenant_a, user_in, as_user)
    with schema_context(tenant_a.schema_name):
        student = create_student(branch=branch, phone="+998905557011")
    # a teacher has students:read but not students:write -> 403
    teacher = as_user(tenant_a, user_in(tenant_a, roles=[Role.TEACHER], branch=branch))
    resp = teacher.post(f"/api/v1/students/{student.id}/block/", {"reason": "x"}, format="json")
    assert resp.status_code == 403
