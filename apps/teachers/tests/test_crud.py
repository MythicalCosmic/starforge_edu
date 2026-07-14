"""Teacher CRUD over the layered (off-DRF) views: success/data + paginated envelopes,
branch scoping, and per-perm authz."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db
URL = "/api/v1/teachers/"


def test_director_create_list_retrieve_delete(tenant_a, as_role):
    from apps.org.tests.factories import BranchFactory

    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()

    resp = client.post(
        URL, {"branch": branch.id, "phone": "+998905550001", "first_name": "Ann"}, format="json"
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["success"] is True
    tid = body["data"]["id"]
    assert body["data"]["first_name"] == "Ann"
    assert "user" not in body["data"]

    listed = client.get(URL).json()
    assert listed["success"] is True
    assert "pagination" in listed
    assert any(t["id"] == tid for t in listed["data"])

    one = client.get(f"{URL}{tid}/").json()
    assert one["data"]["id"] == tid

    assert client.delete(f"{URL}{tid}/").status_code == 204
    assert client.get(f"{URL}{tid}/").status_code == 404


def test_create_accepts_custom_teacher_account_type(tenant_a, as_role):
    from apps.access.models import AccountType, AccountTypePermission
    from apps.org.tests.factories import BranchFactory
    from apps.teachers.models import TeacherProfile

    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        account_type = AccountType.objects.create(
            name="Remote Instructor",
            slug="remote-instructor",
            account_kind=AccountType.AccountKind.TEACHER,
        )
        AccountTypePermission.objects.create(
            account_type=account_type,
            permission="content:read",
        )

    response = client.post(
        URL,
        {
            "branch": branch.pk,
            "account_type": account_type.pk,
            "phone": "+998905550099",
            "first_name": "Remote",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assignments = response.json()["data"]["account_type_assignments"]
    assert [item["account_type_slug"] for item in assignments] == ["remote-instructor"]
    assert all("user" not in item and "role" not in item for item in assignments)

    with schema_context(tenant_a.schema_name):
        teacher = TeacherProfile.objects.get(pk=response.json()["data"]["id"])
        membership = teacher.user.role_memberships.get()
        assert membership.account_type_id == account_type.pk

    updated = client.patch(
        f"{URL}{response.json()['data']['id']}/",
        {"last_name": "Instructor"},
        format="json",
    )
    assert updated.status_code == 200, updated.content
    assert [item["account_type_slug"] for item in updated.json()["data"]["account_type_assignments"]] == [
        "remote-instructor"
    ]


def test_create_requires_phone_or_email(tenant_a, as_role):
    from apps.org.tests.factories import BranchFactory

    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
    resp = client.post(URL, {"branch": branch.id, "first_name": "NoContact"}, format="json")
    assert resp.status_code == 422
    assert "phone" in resp.json()["errors"]


def test_list_is_branch_scoped(tenant_a, user_in, as_user):
    from apps.org.tests.factories import BranchFactory
    from apps.teachers.tests.factories import TeacherProfileFactory

    with schema_context(tenant_a.schema_name):
        branch_a = BranchFactory()
        branch_b = BranchFactory()
        mine = TeacherProfileFactory(branch=branch_a)
        theirs = TeacherProfileFactory(branch=branch_b)
    # A registrar scoped to branch_a (teachers:read, non-director) sees only branch_a.
    client = as_user(tenant_a, user_in(tenant_a, roles=["registrar"], branch=branch_a))
    ids = {t["id"] for t in client.get(URL).json()["data"]}
    assert mine.id in ids
    assert theirs.id not in ids


def test_role_without_teachers_read_is_denied(tenant_a, as_role):
    client, _ = as_role(Role.CASHIER)  # cashier holds no teachers permission
    assert client.get(URL).status_code == 403


def test_list_emits_branch_and_department_names(tenant_a, user_in, as_user):
    """The list rows carry readable `branch_name`/`department_name` next to the bare ids
    so a client needs no second call (select_related keeps it 1 query)."""
    from apps.org.tests.factories import BranchFactory, DepartmentFactory
    from apps.teachers.tests.factories import TeacherProfileFactory

    with schema_context(tenant_a.schema_name):
        branch = BranchFactory(name="North Campus")
        department = DepartmentFactory(branch=branch, name="Mathematics")
        teacher = TeacherProfileFactory(branch=branch, department=department)

    client = as_user(tenant_a, user_in(tenant_a, roles=["registrar"], branch=branch))
    rows = {t["id"]: t for t in client.get(URL).json()["data"]}
    row = rows[teacher.id]
    assert row["branch"] == branch.id
    assert row["branch_name"] == "North Campus"
    assert row["department"] == department.id
    assert row["department_name"] == "Mathematics"
