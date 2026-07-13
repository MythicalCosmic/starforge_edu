"""Launch-blocker regressions for role-native authentication boundaries."""

import re

import pytest
from django.conf import settings
from django.contrib.auth.hashers import is_password_usable
from django.test import RequestFactory
from django_tenants.utils import schema_context

from core.exceptions import PermissionException

pytestmark = pytest.mark.django_db

ROLE_LOGIN_URL = "/api/v1/auth/role-login/"
RESET_REQUEST_URL = "/api/v1/auth/password/reset/request/"
RESET_CONFIRM_URL = "/api/v1/auth/password/reset/confirm/"
PASSWORD = "Quasar-Lantern-42"
NEW_PASSWORD = "Nebula-Compass-77"


def _code_from(sms_text: str) -> str:
    match = re.search(rf"\b(\d{{{settings.OTP_LENGTH}}})\b", sms_text)
    assert match
    return match.group(1)


def test_admin_linked_staff_profile_cannot_role_login_or_request_reset(tenant_a, client_for, sms_outbox):
    from apps.org.models import StaffProfile
    from apps.users.models import OTP, User

    with schema_context(tenant_a.schema_name):
        admin = User.objects.create_superuser(username="platform-admin", password=PASSWORD)
        staff = StaffProfile(
            user=admin,
            username="platform-admin-role",
            phone="+998901110011",
        )
        staff.set_password(PASSWORD)
        staff.save()

    client = client_for(tenant_a)
    login = client.post(
        ROLE_LOGIN_URL,
        {"username": staff.username, "password": PASSWORD},
        format="json",
    )
    assert login.status_code == 401
    assert login.json()["code"] == "invalid_credentials"

    requested = client.post(
        RESET_REQUEST_URL,
        {"identifier": staff.phone, "account_type": "staff"},
        format="json",
    )
    assert requested.status_code == 202
    assert sms_outbox == []
    with schema_context(tenant_a.schema_name):
        assert not OTP.objects.filter(identifier=staff.phone).exists()
        from core.session_auth import create_session, validate_session_key

        legacy_role_session = create_session(
            admin,
            principal_kind="staff",
            principal_id=staff.pk,
        )
        assert validate_session_key(legacy_role_session.key) is None
        # Even a reset capability created before this guard (or by an internal
        # caller) cannot be used against an administrator-linked role profile.
        from apps.auth.services import send_otp

        send_otp(
            identifier=staff.phone,
            purpose=OTP.PURPOSE_RESET,
            target_kind="staff",
            target_id=staff.pk,
        )
    code = _code_from(sms_outbox[0]["text"])
    rejected_reset = client.post(
        RESET_CONFIRM_URL,
        {
            "identifier": staff.phone,
            "account_type": "staff",
            "code": code,
            "new_password": NEW_PASSWORD,
        },
        format="json",
    )
    assert rejected_reset.status_code == 400
    with schema_context(tenant_a.schema_name):
        admin.refresh_from_db()
        staff.refresh_from_db()
        assert admin.check_password(PASSWORD)
        assert staff.check_password(PASSWORD)


def test_reset_otp_is_bound_to_exact_role_when_contact_is_shared(tenant_a, client_for, sms_outbox):
    from apps.students.tests.factories import StudentProfileFactory
    from apps.teachers.tests.factories import TeacherProfileFactory

    shared_phone = "+998901110012"
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory(username="shared-student", phone=shared_phone)
        teacher = TeacherProfileFactory(username="shared-teacher", phone=shared_phone)
        student.set_password(PASSWORD)
        teacher.set_password(PASSWORD)
        student.save(update_fields=["password"])
        teacher.save(update_fields=["password"])
        student_id = student.pk
        teacher_id = teacher.pk

    client = client_for(tenant_a)
    requested = client.post(
        RESET_REQUEST_URL,
        {"identifier": shared_phone, "account_type": "student"},
        format="json",
    )
    assert requested.status_code == 202
    code = _code_from(sms_outbox[0]["text"])

    redirected = client.post(
        RESET_CONFIRM_URL,
        {
            "identifier": shared_phone,
            "account_type": "teacher",
            "code": code,
            "new_password": NEW_PASSWORD,
        },
        format="json",
    )
    assert redirected.status_code == 400

    accepted = client.post(
        RESET_CONFIRM_URL,
        {
            "identifier": shared_phone,
            "account_type": "student",
            "code": code,
            "new_password": NEW_PASSWORD,
        },
        format="json",
    )
    assert accepted.status_code == 204
    with schema_context(tenant_a.schema_name):
        student.refresh_from_db()
        teacher.refresh_from_db()
        assert student.pk == student_id
        assert student.check_password(NEW_PASSWORD)
        assert teacher.pk == teacher_id
        assert teacher.check_password(PASSWORD)


def test_role_session_revalidates_profile_and_bridge_on_every_request(tenant_a):
    from apps.students.models import StudentProfile
    from apps.students.tests.factories import StudentProfileFactory
    from core.session_auth import create_session, validate_session_key

    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory(username="live-principal")
        session = create_session(
            student.user,
            principal_kind="student",
            principal_id=student.pk,
        )
        assert validate_session_key(session.key) is not None

        # Simulate an out-of-band profile deactivation that did not touch the bridge
        # or session row. Live principal validation must still reject it immediately.
        StudentProfile.objects.filter(pk=student.pk).update(is_active=False)
        assert validate_session_key(session.key) is None


def test_profile_delete_disables_bridge_grants_devices_and_sessions(tenant_a):
    from apps.org.tests.factories import BranchFactory
    from apps.students.tests.factories import StudentProfileFactory
    from apps.users.models import Device, RoleMembership, Session, User
    from core.session_auth import create_session

    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory(username="delete-principal")
        user_id = student.user_id
        membership = RoleMembership.objects.create(
            user_id=user_id,
            branch=BranchFactory(),
            role="student",
        )
        device = Device.objects.create(user_id=user_id, device_id="phone-1", platform="android")
        session = create_session(
            student.user,
            principal_kind="student",
            principal_id=student.pk,
        )

        student.delete()  # exercises the shared pre-delete safety net

        bridge = User.objects.get(pk=user_id)
        membership.refresh_from_db()
        device.refresh_from_db()
        stored_session = Session.objects.get(pk=session.pk)
        assert bridge.is_active is False
        assert not is_password_usable(bridge.password)
        assert membership.revoked_at is not None
        assert device.revoked_at is not None
        assert stored_session.revoked_at is not None


def test_profile_deactivation_revokes_bridge_grants_and_sessions(tenant_a):
    from apps.org.tests.factories import BranchFactory
    from apps.students.tests.factories import StudentProfileFactory
    from apps.users.models import RoleMembership, Session
    from apps.users.services import update_role_identity
    from core.session_auth import create_session

    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory(username="deactivate-principal")
        membership = RoleMembership.objects.create(
            user=student.user,
            branch=BranchFactory(),
            role="student",
        )
        session = create_session(
            student.user,
            principal_kind="student",
            principal_id=student.pk,
        )

        update_role_identity(student, {"is_active": False})

        student.refresh_from_db()
        student.user.refresh_from_db()
        membership.refresh_from_db()
        stored_session = Session.objects.get(pk=session.pk)
        assert student.is_active is False
        assert student.user.is_active is False
        assert not student.has_usable_password()
        assert not student.user.has_usable_password()
        assert membership.revoked_at is not None
        assert stored_session.revoked_at is not None


def test_read_only_session_centrally_rejects_unsafe_method(tenant_a, user_in):
    from core.session_auth import SessionAuthentication, create_session

    user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        session = create_session(user, read_only=True)
        request = RequestFactory().post("/any-write/")
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {session.key}"
        with pytest.raises(PermissionException) as exc_info:
            SessionAuthentication().authenticate(request)
        assert exc_info.value.code == "read_only_token"
