import pytest
from django_tenants.utils import schema_context

from apps.org.tests.factories import BranchFactory
from apps.students.models import StudentProfile
from apps.students.services import create_student, transition_enrollment
from core.exceptions import ValidationException

pytestmark = pytest.mark.django_db


def test_create_student_generates_patterned_id(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        student = create_student(branch=branch, phone="+998905551001", first_name="A", last_name="B")
        # pattern {CODE}-{YYYY}-{NNNNN}; CODE defaults to the upper-cased schema.
        assert student.student_id.startswith("TENANT_A-")
        assert student.student_id.endswith("00001")


def test_student_id_sequence_increments(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        first = create_student(branch=branch, phone="+998905551002")
        second = create_student(branch=branch, phone="+998905551003")
        assert first.student_id != second.student_id


def test_legal_transition_records_event_and_sets_enrollment_date(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        student = create_student(branch=branch, phone="+998905551004")
        assert student.status == StudentProfile.Status.LEAD
        transition_enrollment(student=student, to_status=StudentProfile.Status.APPLICATION)
        transition_enrollment(student=student, to_status=StudentProfile.Status.ACCEPTED)
        transition_enrollment(student=student, to_status=StudentProfile.Status.ENROLLED)
        assert student.status == StudentProfile.Status.ENROLLED
        assert student.enrollment_date is not None
        assert student.enrollment_events.count() == 3


def test_illegal_transition_rejected(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        student = create_student(branch=branch, phone="+998905551005")
        with pytest.raises(ValidationException) as exc:
            transition_enrollment(student=student, to_status=StudentProfile.Status.ACTIVE)
        assert exc.value.code == "invalid_transition"
