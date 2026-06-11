"""medical_notes protection: Fernet-encrypted at rest (TD-11 / D1-LD-1) and
role-gated on the API (DoD #4 — only DIRECTOR/REGISTRAR read the plaintext)."""

from __future__ import annotations

import pytest
from django.db import connection
from django_tenants.utils import schema_context

from apps.org.tests.factories import BranchFactory
from apps.students.models import StudentProfile
from apps.students.services import create_student
from core.permissions import Role

pytestmark = pytest.mark.django_db

SECRET = "peanut allergy; carries epipen"


def test_medical_notes_encrypted_at_rest(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory.create()
        student = create_student(branch=branch, phone="+998905553001", medical_notes=SECRET)
        table = StudentProfile._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT medical_notes FROM {table} WHERE id = %s", [student.pk])
            raw = cursor.fetchone()[0]
        assert raw != SECRET
        assert raw.startswith("gAAAA")  # Fernet token marker
        student.refresh_from_db()
        assert student.medical_notes == SECRET  # ORM round-trip decrypts


@pytest.fixture
def student_with_notes(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory.create()
        student = create_student(branch=branch, phone="+998905553002", medical_notes=SECRET)
    return branch, student


def test_list_payload_has_no_medical_notes_key(tenant_a, user_in, as_user, student_with_notes):
    branch, _student = student_with_notes
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.REGISTRAR], branch=branch))
    body = client.get("/api/v1/students/").json()
    assert body["results"]
    assert all("medical_notes" not in row for row in body["results"])


def test_teacher_retrieve_gets_null_medical_notes(tenant_a, user_in, as_user, student_with_notes):
    branch, student = student_with_notes
    client = as_user(tenant_a, user_in(tenant_a, roles=[Role.TEACHER], branch=branch))
    resp = client.get(f"/api/v1/students/{student.id}/")
    assert resp.status_code == 200
    assert resp.json()["medical_notes"] is None


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.DIRECTOR])
def test_medical_roles_retrieve_plaintext(tenant_a, user_in, as_user, student_with_notes, role):
    branch, student = student_with_notes
    client = as_user(tenant_a, user_in(tenant_a, roles=[role], branch=branch))
    resp = client.get(f"/api/v1/students/{student.id}/")
    assert resp.status_code == 200
    assert resp.json()["medical_notes"] == SECRET
