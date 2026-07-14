"""Canonical account-type authorization and assignment regressions."""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django_tenants.utils import schema_context

from apps.access.models import AccountType, AccountTypePermission
from apps.org.services import create_staff_account
from core.permissions import ROLE_PERMISSION_MATRIX, Role

pytestmark = pytest.mark.django_db

TYPES = "/api/v1/access/types/"


def test_system_types_seed_matrix_and_new_memberships_link_canonically(tenant_a, as_role):
    _client, user = as_role(Role.TEACHER)
    with schema_context(tenant_a.schema_name):
        assert AccountType.objects.filter(is_system=True).count() == len(Role.ALL)
        teacher_type = AccountType.objects.get(slug=Role.TEACHER, is_system=True)
        assert set(teacher_type.permission_rows.values_list("permission", flat=True)) == set(
            ROLE_PERMISSION_MATRIX[Role.TEACHER]
        )
        membership = user.role_memberships.get(role=Role.TEACHER)
        assert membership.account_type_id == teacher_type.pk
        # Exercise the migration's forward/backfill function against a row that
        # predates the FK, rather than only relying on the model's new-write hook.
        user.role_memberships.filter(pk=membership.pk).update(account_type_id=None)
        migration = importlib.import_module("apps.users.migrations.0006_rolemembership_account_type")
        migration.link_legacy_memberships(django_apps, connection.schema_editor())
        membership.refresh_from_db()
        assert membership.account_type_id == teacher_type.pk
        user.role_memberships.filter(pk=membership.pk).update(account_type_id=None)
        membership.refresh_from_db()
        membership.save(update_fields=("role",))
        membership.refresh_from_db()
        assert membership.account_type_id == teacher_type.pk


def test_role_profile_provisioning_uses_account_types_and_preserves_custom_memberships(
    tenant_a,
):
    from apps.access.admin import AccountTypePermissionAdminForm
    from apps.org.admin import StaffProfileAdminForm
    from apps.org.tests.factories import BranchFactory
    from apps.teachers.admin import TeacherProfileAdminForm
    from apps.users.admin import RoleMembershipAdmin
    from apps.users.models import RoleMembership
    from apps.users.presenters import role_membership_to_dict
    from apps.users.services import ensure_role_membership

    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        moved_branch = BranchFactory()
        staff = create_staff_account(
            branch=branch,
            role=Role.SUPPORT,
            first_name="Permission",
            last_name="Native",
        )
        system_type = AccountType.objects.get(is_system=True, slug=Role.SUPPORT)
        system_membership = staff.user.role_memberships.get(account_type=system_type)
        assert system_membership.account_type_id == system_type.pk

        custom_type = AccountType.objects.create(
            name="Custom Staff Scope",
            slug="custom-staff-scope",
            account_kind=AccountType.AccountKind.STAFF,
        )
        custom_membership = RoleMembership.objects.create(
            user=staff.user,
            account_type=custom_type,
            role=custom_type.compatibility_role,
            branch=branch,
        )
        ensure_role_membership(
            staff,
            role=Role.SUPPORT,
            branch=moved_branch,
        )
        system_membership.refresh_from_db()
        custom_membership.refresh_from_db()
        assert system_membership.account_type_id == system_type.pk
        assert system_membership.branch_id == moved_branch.pk
        assert custom_membership.account_type_id == custom_type.pk
        assert custom_membership.branch_id == branch.pk

        payload = role_membership_to_dict(system_membership)
        assert payload["account_type_name"] == system_type.name
        assert payload["account_kind"] == AccountType.AccountKind.STAFF
        assert "role" not in payload
        assert "legacy_role" not in payload

    assert "account_type" in StaffProfileAdminForm.base_fields
    assert "role" not in StaffProfileAdminForm.base_fields
    assert "account_type" in TeacherProfileAdminForm.base_fields
    assert "user" not in RoleMembershipAdmin.fields
    assert "role" not in RoleMembershipAdmin.fields
    assert RoleMembership._meta.verbose_name == "Account type assignment"

    permission_form = AccountTypePermissionAdminForm()
    choice_codes = {value for value, _label in permission_form.fields["permission"].choices}
    delegable_defaults = {
        permission
        for permissions in ROLE_PERMISSION_MATRIX.values()
        for permission in permissions
        if permission != "*:*" and not permission.startswith("access:")
    }
    assert delegable_defaults <= choice_codes


def test_custom_staff_permissions_take_effect_immediately_and_are_branch_scoped(
    tenant_a,
    as_role,
    as_user,
):
    from apps.audit.models import AuditLog
    from apps.finance.tests.factories import InvoiceFactory
    from apps.org.tests.factories import BranchFactory
    from apps.schedule.models import TimeSlot
    from apps.students.tests.factories import StudentProfileFactory
    from apps.tasks.models import Task

    director, _director_user = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        other_branch = BranchFactory()
        staff = create_staff_account(branch=branch, role=Role.SUPPORT, first_name="Case", last_name="Worker")
        visible_student = StudentProfileFactory(branch=branch)
        hidden_student = StudentProfileFactory(branch=other_branch)

    response = director.post(
        TYPES,
        {
            "name": "Counselor",
            "slug": "counselor",
            "account_kind": "staff",
            "permissions": ["notifications:read"],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    account_type_id = response.json()["data"]["id"]
    assignment = director.post(
        f"{TYPES}{account_type_id}/assignments/",
        {
            "principal_kind": "staff",
            "principal_id": staff.pk,
            "branch": branch.pk,
        },
        format="json",
    )
    assert assignment.status_code == 201, assignment.content
    assignment_body = assignment.json()["data"]
    assert assignment_body["principal_kind"] == "staff"
    assert assignment_body["principal_id"] == staff.pk
    assert "user" not in assignment_body

    # Give the same principal an unrelated, non-resource account type in Branch
    # B. Every resource assertion below proves its scope cannot be borrowed by
    # the Branch-A grant.
    decoy = director.post(
        TYPES,
        {
            "name": "Remote Notices",
            "slug": "remote-notices",
            "account_kind": "staff",
            "permissions": ["notifications:read"],
        },
        format="json",
    )
    assert decoy.status_code == 201, decoy.content
    decoy_assignment = director.post(
        f"{TYPES}{decoy.json()['data']['id']}/assignments/",
        {
            "principal_kind": "staff",
            "principal_id": staff.pk,
            "branch": other_branch.pk,
        },
        format="json",
    )
    assert decoy_assignment.status_code == 201, decoy_assignment.content

    with schema_context(tenant_a.schema_name):
        visible_slot = TimeSlot.objects.create(
            branch=branch,
            name="Morning",
            start_time="09:00",
            end_time="10:00",
        )
        hidden_slot = TimeSlot.objects.create(
            branch=other_branch,
            name="Remote morning",
            start_time="09:00",
            end_time="10:00",
        )
        visible_invoice = InvoiceFactory(student=visible_student)
        hidden_invoice = InvoiceFactory(student=hidden_student)
        visible_task = Task.objects.create(
            title="Local follow-up",
            branch=branch,
            created_by=_director_user,
        )
        hidden_task = Task.objects.create(
            title="Remote follow-up",
            branch=other_branch,
            created_by=_director_user,
        )

    # Mint once after the assignment. Permission/type edits below do not rotate
    # the token; the same live session observes each change on its next request.
    with schema_context(tenant_a.schema_name):
        staff.user.refresh_from_db()
    staff_client = as_user(tenant_a, staff.user)
    assert staff_client.get("/api/v1/students/").status_code == 403

    update = director.put(
        f"{TYPES}{account_type_id}/permissions/",
        {
            "permissions": [
                "notifications:read",
                "students:read",
                "schedule:read",
                "finance:read",
                "intelligence:read",
                "tasks:read",
                "tasks:write",
            ]
        },
        format="json",
    )
    assert update.status_code == 200, update.content
    students = staff_client.get("/api/v1/students/")
    assert students.status_code == 200, students.content
    ids = {item["id"] for item in students.json()["data"]}
    assert visible_student.pk in ids
    assert hidden_student.pk not in ids

    slots = staff_client.get("/api/v1/schedule/timeslots/")
    assert slots.status_code == 200, slots.content
    slot_ids = {item["id"] for item in slots.json()["data"]}
    assert visible_slot.pk in slot_ids
    assert hidden_slot.pk not in slot_ids

    invoices = staff_client.get("/api/v1/finance/invoices/")
    assert invoices.status_code == 200, invoices.content
    invoice_ids = {item["id"] for item in invoices.json()["data"]}
    assert visible_invoice.pk in invoice_ids
    assert hidden_invoice.pk not in invoice_ids

    branches = staff_client.get("/api/v1/intelligence/branches/")
    assert branches.status_code == 200, branches.content
    branch_ids = {item["branch"] for item in branches.json()["data"]["results"]}
    assert branch.pk in branch_ids
    assert other_branch.pk not in branch_ids

    tasks = staff_client.get("/api/v1/tasks/")
    assert tasks.status_code == 200, tasks.content
    task_ids = {item["id"] for item in tasks.json()["data"]}
    assert visible_task.pk in task_ids
    assert hidden_task.pk not in task_ids

    effective = director.get(
        f"{TYPES}effective-permissions/",
        {"principal_kind": "staff", "principal_id": staff.pk},
    )
    assert effective.status_code == 200
    assert "students:read" in effective.json()["data"]["permissions"]

    disabled = director.patch(
        f"{TYPES}{account_type_id}/",
        {"is_active": False},
        format="json",
    )
    assert disabled.status_code == 200
    assert staff_client.get("/api/v1/students/").status_code == 403
    assert (
        director.patch(
            f"{TYPES}{account_type_id}/",
            {"is_active": True},
            format="json",
        ).status_code
        == 200
    )
    assert staff_client.get("/api/v1/students/").status_code == 200

    with schema_context(tenant_a.schema_name):
        assert AuditLog.objects.filter(
            resource_type="access.account_type", resource_id=account_type_id
        ).exists()
        assert AuditLog.objects.filter(
            resource_type="access.account_type_assignment",
            resource_id=assignment_body["id"],
        ).exists()


@pytest.mark.parametrize("permission", ["*: *", "*:*", "access:*", "access:write"])
def test_custom_type_rejects_owner_permissions(tenant_a, as_role, permission):
    director, _ = as_role(Role.DIRECTOR)
    response = director.post(
        TYPES,
        {
            "name": f"Unsafe {permission}",
            "slug": f"unsafe-{abs(hash(permission))}",
            "account_kind": "staff",
            "permissions": [permission],
        },
        format="json",
    )
    assert response.status_code == 400


def test_owner_type_is_protected_and_model_validation_cannot_bypass_reservation(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        owner = AccountType.objects.get(slug=Role.DIRECTOR, is_system=True)
        custom = AccountType.objects.create(
            name="Restricted Test",
            slug="restricted-test",
            account_kind=AccountType.AccountKind.STAFF,
        )
        with pytest.raises(DjangoValidationError):
            AccountTypePermission.objects.create(account_type=custom, permission="*:* ")

    protected = director.put(
        f"{TYPES}{owner.pk}/permissions/",
        {"permissions": ["students:read"]},
        format="json",
    )
    assert protected.status_code == 409
    assert protected.json()["code"] == "protected_account_type"


def test_assignment_validates_principal_kind_and_can_be_revoked_without_user_ids(
    tenant_a,
    as_role,
):
    from apps.org.tests.factories import BranchFactory

    director, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        staff = create_staff_account(branch=branch, role=Role.SUPPORT, first_name="Scoped")
    created = director.post(
        TYPES,
        {
            "name": "Admissions Helper",
            "slug": "admissions-helper",
            "account_kind": "staff",
            "permissions": ["students:read"],
        },
        format="json",
    )
    account_type_id = created.json()["data"]["id"]
    mismatch = director.post(
        f"{TYPES}{account_type_id}/assignments/",
        {
            "principal_kind": "teacher",
            "principal_id": staff.pk,
            "branch": branch.pk,
        },
        format="json",
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "principal_kind_mismatch"

    assigned = director.post(
        f"{TYPES}{account_type_id}/assignments/",
        {
            "principal_kind": "staff",
            "principal_id": staff.pk,
            "branch": branch.pk,
        },
        format="json",
    )
    assignment_id = assigned.json()["data"]["id"]
    assert director.delete(f"{TYPES}assignments/{assignment_id}/").status_code == 204
    assert director.delete(f"{TYPES}{account_type_id}/").status_code == 204


def test_permission_catalog_includes_granular_task_transition_and_all_roles_notifications(
    tenant_a,
    as_role,
):
    director, _ = as_role(Role.DIRECTOR)
    response = director.get("/api/v1/access/permissions/")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "tasks:transition_any" in data["permissions"]
    detail = next(item for item in data["permission_details"] if item["code"] == "tasks:transition_any")
    assert detail["label"]
    assert detail["description"]
    for role in Role.ALL:
        if role != Role.DIRECTOR:
            assert "notifications:read" in ROLE_PERMISSION_MATRIX[role]


def test_custom_permission_scope_and_recipient_discovery_cannot_borrow_another_branch(
    tenant_a,
    as_user,
):
    from django.utils import timezone

    from apps.campaigns.models import Campaign
    from apps.org.tests.factories import BranchFactory
    from apps.users.models import RoleMembership
    from core.permissions import role_memberships_with_permission

    with schema_context(tenant_a.schema_name):
        local_branch = BranchFactory()
        remote_branch = BranchFactory()
        staff = create_staff_account(
            branch=local_branch,
            role=Role.SUPPORT,
            first_name="Exact",
            last_name="Scope",
        )
        # Remove the provisioning compatibility membership so this regression
        # exercises only the two custom AccountTypes below.
        staff.user.role_memberships.update(revoked_at=timezone.now())

        local_type = AccountType.objects.create(
            name="Local Campaign Operator",
            slug="local-campaign-operator",
            account_kind=AccountType.AccountKind.STAFF,
        )
        AccountTypePermission.objects.create(account_type=local_type, permission="campaign:read")
        AccountTypePermission.objects.create(account_type=local_type, permission="cover:approve")
        local_membership = RoleMembership.objects.create(
            user=staff.user,
            account_type=local_type,
            role=local_type.compatibility_role,
            branch=local_branch,
        )

        remote_type = AccountType.objects.create(
            name="Remote Notices Only",
            slug="remote-notices-only",
            account_kind=AccountType.AccountKind.STAFF,
        )
        AccountTypePermission.objects.create(account_type=remote_type, permission="notifications:read")
        RoleMembership.objects.create(
            user=staff.user,
            account_type=remote_type,
            role=remote_type.compatibility_role,
            branch=remote_branch,
        )
        local_campaign = Campaign.objects.create(
            name="Local",
            message="Local",
            branch=local_branch,
            created_by=staff.user,
        )
        remote_campaign = Campaign.objects.create(
            name="Remote",
            message="Remote",
            branch=remote_branch,
        )

        recipients = role_memberships_with_permission("cover:approve").filter(user=staff.user)
        assert list(recipients.values_list("pk", flat=True)) == [local_membership.pk]

    client = as_user(tenant_a, staff.user)
    response = client.get("/api/v1/campaigns/")
    assert response.status_code == 200, response.content
    campaign_ids = {item["id"] for item in response.json()["data"]}
    assert local_campaign.pk in campaign_ids
    assert remote_campaign.pk not in campaign_ids
