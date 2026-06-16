"""Receiver wiring + EventType canonical-list verification (D3-C-2/4).

Per the Day-1 review lesson ("test wiring, not imports"): assert the receivers
are actually CONNECTED to the source signals (not merely importable), and that
the EventType enum matches the DAY-3 D3-C-2 canonical list verbatim.
"""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from apps.notifications.models import EventType, Notification

pytestmark = pytest.mark.django_db

# The canonical D3-C-2 list (extend, never rename).
CANONICAL_EVENT_TYPES = {
    "attendance.absent",
    "attendance.late",
    "academics.grades_published",
    "assignments.created",
    "assignments.due_soon",
    "assignments.graded",
    "schedule.lesson_reminder",
    "auth.new_device_login",
    "students.enrollment_changed",
    "finance.invoice_issued",
    "finance.payment_reminder",
    "payments.payment_completed",
    "payments.payment_failed",
    "cohorts.announcement",
    "billing.subscription_past_due",
    "billing.subscription_suspended",
}


def test_event_type_covers_canonical_list():
    values = {choice for choice, _label in EventType.choices}
    # extend-never-rename: every canonical value must be present.
    assert values >= CANONICAL_EVENT_TYPES


def _connected_uids(signal) -> list[str]:
    """The dispatch_uid of each connected receiver.

    Django 6 stores each receiver as a tuple whose first element is the
    ``lookup_key`` ``(dispatch_uid_or_id, sender_id)`` — ``lookup_key[0]`` is the
    dispatch_uid string when one was supplied.
    """
    return [str(entry[0][0]) for entry in signal.receivers]


def test_attendance_signal_receiver_connected():
    """student_marked_absent must have the notifications receiver attached."""
    from apps.attendance.signals import student_marked_absent

    assert any("notifications.student_marked_absent" in uid for uid in _connected_uids(student_marked_absent))


def test_assignment_published_receiver_connected():
    from apps.assignments.signals import assignment_published

    assert any("notifications.assignment_published" in uid for uid in _connected_uids(assignment_published))


def test_auth_login_receiver_connected():
    from apps.auth.signals import login_succeeded

    assert any("notifications.login_succeeded" in uid for uid in _connected_uids(login_succeeded))


def test_cohort_member_moved_bridges_enrollment_changed(tenant_a):
    """cohorts.cohort_member_moved -> students.enrollment_changed notification."""
    from apps.cohorts.signals import cohort_member_moved
    from apps.students.tests.factories import StudentProfileFactory

    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        cohort_member_moved.send(
            sender=None,
            student_id=student.pk,
            to_cohort_id=7,
            schema_name=tenant_a.schema_name,
        )
        notif = Notification.objects.filter(user=student.user).first()
        assert notif is not None
        assert notif.event_type == EventType.STUDENTS_ENROLLMENT_CHANGED
