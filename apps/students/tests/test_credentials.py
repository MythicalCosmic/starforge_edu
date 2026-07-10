"""Staff-issued student login credentials (owner: "where to enter their login and
password they can actually login?"). Student accounts are created passwordless
(set_unusable_password); staff set a password via the credentials endpoint so the
account becomes usable, and the login username is exposed so staff can hand it over."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from apps.org.tests.factories import BranchFactory
from apps.students.models import StudentProfile
from apps.students.services import create_student
from core.permissions import Role

pytestmark = pytest.mark.django_db

STRONG = "Str0ng-Passw0rd-2026!"


def _registrar_and_student(tenant, user_in, as_user):
    with schema_context(tenant.schema_name):
        branch = BranchFactory.create()
        sid = create_student(branch=branch, phone="+998905559001").id
    client = as_user(tenant, user_in(tenant, roles=[Role.REGISTRAR], branch=branch))
    return branch, client, sid


def test_staff_sets_password_and_student_can_authenticate(tenant_a, user_in, as_user):
    _, client, sid = _registrar_and_student(tenant_a, user_in, as_user)
    with schema_context(tenant_a.schema_name):
        assert StudentProfile.objects.get(pk=sid).user.has_usable_password() is False  # born passwordless

    resp = client.post(f"/api/v1/students/{sid}/credentials/", {"password": STRONG}, format="json")
    assert resp.status_code == 200, resp.content
    username = resp.json()["data"]["username"]
    assert username

    with schema_context(tenant_a.schema_name):
        user = StudentProfile.objects.get(pk=sid).user
        assert user.username == username
        assert user.check_password(STRONG)  # the account is now usable — the login gap is closed


def test_weak_password_rejected(tenant_a, user_in, as_user):
    _, client, sid = _registrar_and_student(tenant_a, user_in, as_user)
    resp = client.post(f"/api/v1/students/{sid}/credentials/", {"password": "123"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["code"] == "weak_password"


def test_missing_password_rejected(tenant_a, user_in, as_user):
    _, client, sid = _registrar_and_student(tenant_a, user_in, as_user)
    resp = client.post(f"/api/v1/students/{sid}/credentials/", {}, format="json")
    assert resp.status_code == 400


def test_teacher_cannot_set_credentials(tenant_a, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory.create()
        sid = create_student(branch=branch, phone="+998905559002").id
    teacher = as_user(tenant_a, user_in(tenant_a, roles=[Role.TEACHER], branch=branch))
    resp = teacher.post(f"/api/v1/students/{sid}/credentials/", {"password": STRONG}, format="json")
    assert resp.status_code == 403  # students:read but not students:write


def test_username_exposed_in_detail_payload(tenant_a, user_in, as_user):
    _, client, sid = _registrar_and_student(tenant_a, user_in, as_user)
    body = client.get(f"/api/v1/students/{sid}/").json()["data"]
    assert body["user"]["username"]


def test_cannot_set_credentials_for_staff_account(tenant_a, user_in, as_user):
    """Defense in depth: the student endpoint must refuse to reset a staff/superuser
    password even if a StudentProfile were linked to one."""
    _, client, sid = _registrar_and_student(tenant_a, user_in, as_user)
    with schema_context(tenant_a.schema_name):
        sp = StudentProfile.objects.get(pk=sid)
        sp.user.is_staff = True
        sp.user.save(update_fields=["is_staff"])
    resp = client.post(f"/api/v1/students/{sid}/credentials/", {"password": STRONG}, format="json")
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
