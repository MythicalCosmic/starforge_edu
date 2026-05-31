"""Audit: sensitive-model changes are logged, with request-actor attribution."""

from __future__ import annotations

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.org.models import Branch
from apps.students.models import StudentProfile
from apps.users.models import RoleMembership, User
from core.permissions import Role


class AuditSignalTest(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Test Center"
        tenant.slug = "test"

    def setUp(self):
        self.branch = Branch.objects.create(name="Main", slug="main")
        self.student_user = User.objects.create(phone="+998900000011")

    def test_creating_sensitive_model_writes_audit_row(self):
        student = StudentProfile.objects.create(
            user=self.student_user, branch=self.branch, student_id="2026-00001"
        )
        log = AuditLog.objects.get(resource_type="students.StudentProfile", resource_id=str(student.id))
        assert log.action == AuditLog.Action.CREATE

    def test_role_grant_is_audited(self):
        # RoleMembership is the security-critical model — granting a role logs it.
        before = AuditLog.objects.filter(resource_type="users.RoleMembership").count()
        RoleMembership.objects.create(user=self.student_user, branch=self.branch, role=Role.STUDENT)
        after = AuditLog.objects.filter(resource_type="users.RoleMembership").count()
        assert after == before + 1

    def test_api_change_attributes_the_actor(self):
        registrar = User.objects.create(phone="+998900000010")
        RoleMembership.objects.create(user=registrar, branch=self.branch, role=Role.REGISTRAR)

        client = APIClient()
        client.force_authenticate(user=registrar)
        r = client.post(
            "/api/v1/students/",
            {"user": self.student_user.id, "branch": self.branch.id, "status": "active"},
            format="json",
            HTTP_HOST=self.get_test_tenant_domain(),
        )
        assert r.status_code == 201, r.content
        log = AuditLog.objects.get(resource_type="students.StudentProfile", action=AuditLog.Action.CREATE)
        assert log.actor_id == registrar.id
