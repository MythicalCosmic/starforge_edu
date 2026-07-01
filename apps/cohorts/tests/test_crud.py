"""Cohort CRUD over the layered (off-DRF) views: success/data + paginated
envelopes, branch scoping, and per-perm authz. Complements test_membership /
test_branch_scope (which cover the enroll/move/archive action semantics)."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db
URL = "/api/v1/cohorts/"


def test_director_create_list_retrieve_delete(tenant_a, as_role):
    from apps.org.tests.factories import BranchFactory

    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()

    resp = client.post(
        URL,
        {
            "name": "Morning A1",
            "branch": branch.id,
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "level": "A1",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["success"] is True
    cid = body["data"]["id"]
    assert body["data"]["name"] == "Morning A1"
    assert body["data"]["co_teachers"] == []

    listed = client.get(URL).json()
    assert listed["success"] is True
    assert "pagination" in listed
    assert any(c["id"] == cid for c in listed["data"])

    one = client.get(f"{URL}{cid}/").json()
    assert one["data"]["id"] == cid

    assert client.delete(f"{URL}{cid}/").status_code == 204  # empty + unarchived -> deletable
    assert client.get(f"{URL}{cid}/").status_code == 404


def test_create_rejects_end_before_start(tenant_a, as_role):
    from apps.org.tests.factories import BranchFactory

    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
    resp = client.post(
        URL,
        {"name": "Bad", "branch": branch.id, "start_date": "2026-06-30", "end_date": "2026-01-01"},
        format="json",
    )
    assert resp.status_code == 400
    assert "end_date" in resp.json()["errors"]


def test_list_is_branch_scoped(tenant_a, user_in, as_user):
    from apps.cohorts.tests.factories import CohortFactory
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant_a.schema_name):
        branch_a = BranchFactory()
        branch_b = BranchFactory()
        mine = CohortFactory(branch=branch_a)
        theirs = CohortFactory(branch=branch_b)
    # A registrar scoped to branch_a (cohorts:read, non-director) sees only branch_a.
    client = as_user(tenant_a, user_in(tenant_a, roles=["registrar"], branch=branch_a))
    ids = {c["id"] for c in client.get(URL).json()["data"]}
    assert mine.id in ids
    assert theirs.id not in ids


def test_detail_out_of_scope_is_403(tenant_a, user_in, as_user):
    from apps.cohorts.tests.factories import CohortFactory
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant_a.schema_name):
        branch_a = BranchFactory()
        branch_b = BranchFactory()
        theirs = CohortFactory(branch=branch_b)
    client = as_user(tenant_a, user_in(tenant_a, roles=["registrar"], branch=branch_a))
    assert client.get(f"{URL}{theirs.id}/").status_code == 403


def test_role_without_cohorts_read_is_denied(tenant_a, as_role):
    client, _ = as_role(Role.CASHIER)  # cashier holds no cohorts permission
    assert client.get(URL).status_code == 403
