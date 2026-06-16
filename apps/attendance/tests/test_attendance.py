"""Attendance lane tests (D2-B): upsert + late threshold + correction window,
auto-absent idempotency, the guardian-absence signal, summary/dashboard math,
CSV export, role scoping, cross-tenant isolation, and query budgets."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
import time_machine
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.attendance.models import AttendanceRecord
from apps.attendance.services import auto_mark_absent, mark_attendance
from apps.attendance.signals import student_marked_absent
from apps.attendance.tests.factories import AttendanceRecordFactory
from apps.cohorts.tests.factories import CohortFactory, CohortMembershipFactory
from apps.org.models import CenterSettings
from apps.org.tests.factories import BranchFactory
from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
from apps.schedule.models import Lesson
from apps.schedule.tests.factories import TermFactory
from apps.students.tests.factories import StudentProfileFactory
from apps.teachers.tests.factories import TeacherProfileFactory
from core.exceptions import PermissionException, UnprocessableEntity

pytestmark = pytest.mark.django_db

Status = AttendanceRecord.Status


def _aware(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


def _make_lesson(*, branch, teacher, cohort=None, term=None, starts_at=None, ends_at=None) -> Lesson:
    cohort = cohort or CohortFactory(branch=branch)
    term = term or TermFactory()
    starts_at = starts_at or (timezone.now() - timedelta(hours=1))
    ends_at = ends_at or (starts_at + timedelta(hours=1))
    return Lesson.objects.create(
        term=term, cohort=cohort, teacher=teacher, title="Algebra", starts_at=starts_at, ends_at=ends_at
    )


def _enroll(cohort, *, n=1, branch=None) -> list[Any]:
    # factory-boy's typed stubs return the Factory class, not the instance, so the
    # produced rows are kept as Any (repo convention from the schedule lane).
    students: list[Any] = []
    for _ in range(n):
        student = StudentProfileFactory(branch=branch) if branch else StudentProfileFactory()
        CohortMembershipFactory(cohort=cohort, student=student)
        students.append(student)
    return students


# --------------------------------------------------------------------------- #
# mark_attendance — service-level behavior
# --------------------------------------------------------------------------- #


def test_mark_upserts_unique_per_student_lesson(tenant_a, user_in):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        lesson = _make_lesson(branch=branch, teacher=profile)
        (student,) = _enroll(lesson.cohort, branch=branch)

        first = mark_attendance(
            lesson=lesson, entries=[{"student": student, "status": Status.PRESENT}], actor=teacher_user
        )
        assert (first["created"], first["updated"]) == (1, 0)

        second = mark_attendance(
            lesson=lesson, entries=[{"student": student, "status": Status.ABSENT}], actor=teacher_user
        )
        assert (second["created"], second["updated"]) == (0, 1)
        records = AttendanceRecord.objects.filter(lesson=lesson, student=student)
        assert records.count() == 1
        assert records.get().status == Status.ABSENT


def test_teacher_of_other_cohort_denied(tenant_a, user_in):
    owner = user_in(tenant_a, roles=["teacher"])
    intruder = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=owner, branch=branch)
        lesson = _make_lesson(branch=branch, teacher=profile)
        (student,) = _enroll(lesson.cohort, branch=branch)
        with pytest.raises(PermissionException) as exc:
            mark_attendance(
                lesson=lesson, entries=[{"student": student, "status": Status.PRESENT}], actor=intruder
            )
        assert exc.value.code == "not_lesson_teacher"


def test_student_not_in_cohort_rejected(tenant_a, user_in):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        lesson = _make_lesson(branch=branch, teacher=profile)
        outsider: Any = StudentProfileFactory(branch=branch)  # never enrolled
        with pytest.raises(UnprocessableEntity) as exc:
            mark_attendance(
                lesson=lesson, entries=[{"student": outsider, "status": Status.PRESENT}], actor=teacher_user
            )
        assert exc.value.code == "student_not_in_cohort"
        assert outsider.pk in (exc.value.fields or {})["students"]


@pytest.mark.parametrize(
    ("minutes_late", "expected"),
    [(10, Status.PRESENT), (11, Status.LATE)],  # threshold default 10: == present, +1 = late
)
def test_late_threshold_boundary(tenant_a, user_in, minutes_late, expected):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        starts_at = timezone.now() - timedelta(hours=1)
        lesson = _make_lesson(branch=branch, teacher=profile, starts_at=starts_at)
        (student,) = _enroll(lesson.cohort, branch=branch)
        result = mark_attendance(
            lesson=lesson,
            entries=[
                {
                    "student": student,
                    "status": Status.PRESENT,
                    "arrived_at": starts_at + timedelta(minutes=minutes_late),
                }
            ],
            actor=teacher_user,
        )
        assert result["records"][0].status == expected


def test_late_threshold_knob_changes_behavior_no_code_change(tenant_a, user_in):
    """DoD #2 — bumping `late_threshold_minutes` shifts the boundary alone."""
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        from django.core.cache import cache

        settings = CenterSettings.load()
        settings.late_threshold_minutes = 20
        settings.save(update_fields=["late_threshold_minutes"])
        cache.clear()

        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        starts_at = timezone.now() - timedelta(hours=1)
        lesson = _make_lesson(branch=branch, teacher=profile, starts_at=starts_at)
        (student,) = _enroll(lesson.cohort, branch=branch)
        # 15 min late: `late` under the default 10, but `present` under 20.
        result = mark_attendance(
            lesson=lesson,
            entries=[
                {
                    "student": student,
                    "status": Status.PRESENT,
                    "arrived_at": starts_at + timedelta(minutes=15),
                }
            ],
            actor=teacher_user,
        )
        assert result["records"][0].status == Status.PRESENT


def test_correction_window_expired_teacher_403_director_ok(tenant_a, user_in, as_user):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    director_user = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        starts_at = _aware(2026, 6, 1, 10)
        lesson = _make_lesson(
            branch=branch, teacher=profile, starts_at=starts_at, ends_at=starts_at + timedelta(hours=1)
        )
        (student,) = _enroll(lesson.cohort, branch=branch)
        lesson_id, student_id, cohort_id = lesson.id, student.id, lesson.cohort_id

    body = [{"student": student_id, "status": "present"}]
    # Travel to 25h after the lesson ended (default correction window is 24h).
    # Tokens are minted INSIDE the travel so they aren't seen as expired.
    with time_machine.travel(_aware(2026, 6, 2, 12)):
        teacher_client = as_user(tenant_a, teacher_user)
        director_client = as_user(tenant_a, director_user)
        resp_t = teacher_client.post(f"/api/v1/attendance/lessons/{lesson_id}/mark/", body, format="json")
        assert resp_t.status_code == 403
        assert resp_t.json()["error"]["code"] == "correction_window_expired"

        resp_d = director_client.post(f"/api/v1/attendance/lessons/{lesson_id}/mark/", body, format="json")
        assert resp_d.status_code == 200
    with schema_context(tenant_a.schema_name):
        assert AttendanceRecord.objects.filter(lesson_id=lesson_id, student_id=student_id).exists()
        assert cohort_id  # silence unused


# --------------------------------------------------------------------------- #
# auto-absent sweep
# --------------------------------------------------------------------------- #


def test_auto_absent_idempotent_double_run(tenant_a, django_capture_on_commit_callbacks):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(branch=branch)
        starts_at = timezone.now() - timedelta(minutes=40)  # past auto_absent_after (30)
        lesson = _make_lesson(branch=branch, teacher=profile, starts_at=starts_at)
        _enroll(lesson.cohort, n=2, branch=branch)

        with django_capture_on_commit_callbacks(execute=True) as first:
            created_1 = auto_mark_absent()
        with django_capture_on_commit_callbacks(execute=True) as second:
            created_2 = auto_mark_absent()

        assert (created_1, len(first)) == (2, 2)  # 2 records, 2 signals
        assert (created_2, len(second)) == (0, 0)  # idempotent: nothing new
        assert AttendanceRecord.objects.filter(lesson=lesson).count() == 2
        assert AttendanceRecord.objects.filter(lesson=lesson, status=Status.ABSENT).count() == 2


def test_auto_absent_skips_marked_students(tenant_a, user_in):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        starts_at = timezone.now() - timedelta(minutes=40)
        lesson = _make_lesson(branch=branch, teacher=profile, starts_at=starts_at)
        present_student, absent_student = _enroll(lesson.cohort, n=2, branch=branch)
        mark_attendance(
            lesson=lesson,
            entries=[{"student": present_student, "status": Status.PRESENT}],
            actor=teacher_user,
        )

        created = auto_mark_absent()
        assert created == 1  # only the unmarked student
        assert AttendanceRecord.objects.get(lesson=lesson, student=present_student).status == Status.PRESENT
        assert AttendanceRecord.objects.get(lesson=lesson, student=absent_student).status == Status.ABSENT


def test_auto_absent_skips_future_and_cancelled_lessons(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(branch=branch)
        # Started only 5 min ago — inside the 30-min grace window.
        recent = _make_lesson(branch=branch, teacher=profile, starts_at=timezone.now() - timedelta(minutes=5))
        _enroll(recent.cohort, n=1, branch=branch)
        # Old but cancelled.
        cancelled = _make_lesson(
            branch=branch, teacher=profile, starts_at=timezone.now() - timedelta(hours=2)
        )
        cancelled.status = Lesson.Status.CANCELLED
        cancelled.save(update_fields=["status"])
        _enroll(cancelled.cohort, n=1, branch=branch)

        assert auto_mark_absent() == 0
        assert AttendanceRecord.objects.count() == 0


# --------------------------------------------------------------------------- #
# signal
# --------------------------------------------------------------------------- #


def test_absence_signal_emitted_manual_and_auto(tenant_a, user_in, django_capture_on_commit_callbacks):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    received: list[dict] = []

    def _recv(sender, **kwargs):
        received.append(kwargs)

    student_marked_absent.connect(_recv)
    try:
        with schema_context(tenant_a.schema_name):
            branch = BranchFactory()
            profile = TeacherProfileFactory(user=teacher_user, branch=branch)
            starts_at = timezone.now() - timedelta(minutes=40)
            lesson = _make_lesson(branch=branch, teacher=profile, starts_at=starts_at)
            manual_student, auto_student = _enroll(lesson.cohort, n=2, branch=branch)

            with django_capture_on_commit_callbacks(execute=True):
                mark_attendance(
                    lesson=lesson,
                    entries=[{"student": manual_student, "status": Status.ABSENT}],
                    actor=teacher_user,
                )
            assert [k["auto"] for k in received] == [False]

            with django_capture_on_commit_callbacks(execute=True):
                auto_mark_absent()
            # The manually-absent student already has a record; only auto_student fires.
            assert [k["auto"] for k in received] == [False, True]
            assert received[-1]["student_id"] == auto_student.id
    finally:
        student_marked_absent.disconnect(_recv)


# --------------------------------------------------------------------------- #
# summary + dashboard math / budget
# --------------------------------------------------------------------------- #


def test_summary_math(tenant_a):
    from apps.attendance import selectors

    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(branch=branch)
        term: Any = TermFactory()
        cohort = CohortFactory(branch=branch)
        (student,) = _enroll(cohort, branch=branch)
        # 10 records, one per lesson (unique student+lesson): 6 present, 2 absent,
        # 1 late, 1 excused → percent_present = 60.0.
        plan = [Status.PRESENT] * 6 + [Status.ABSENT] * 2 + [Status.LATE, Status.EXCUSED]
        for i, st in enumerate(plan):
            day_start = _aware(2026, 3, 1 + i, 9)
            lesson = _make_lesson(
                branch=branch,
                teacher=profile,
                cohort=cohort,
                term=term,
                starts_at=day_start,
                ends_at=day_start + timedelta(hours=1),
            )
            AttendanceRecordFactory(student=student, lesson=lesson, status=st)

        summary = selectors.term_summary(
            base_qs=AttendanceRecord.objects.all(), student_id=student.id, term_id=term.id
        )
        assert summary == {
            "present": 6,
            "absent": 2,
            "late": 1,
            "excused": 1,
            "percent_present": 60.0,
        }


def test_dashboard_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(branch=branch)
        cohort: Any = CohortFactory(branch=branch)
        lesson = _make_lesson(branch=branch, teacher=profile, cohort=cohort)
        students = _enroll(cohort, n=30, branch=branch)
        for student in students:
            AttendanceRecordFactory(student=student, lesson=lesson, status=Status.PRESENT)
        cohort_id = cohort.id

    client = as_user(tenant_a, director)
    with django_assert_max_num_queries(5):
        resp = client.get(f"/api/v1/attendance/cohorts/{cohort_id}/dashboard/")
    body = resp.json()
    assert resp.status_code == 200
    assert len(body["students"]) == 30
    assert body["rate"] == 100.0


# --------------------------------------------------------------------------- #
# API surface — gating, scoping, export, cross-tenant, budget
# --------------------------------------------------------------------------- #


def test_mark_requires_write_perm(tenant_a, as_role):
    from core.permissions import Role

    client, _ = as_role(Role.STUDENT)  # student has attendance:read, not :write
    resp = client.post("/api/v1/attendance/lessons/1/mark/", [], format="json")
    assert resp.status_code == 403


def test_records_list_scoping_student_parent_teacher(tenant_a, user_in, as_user):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    student_user = user_in(tenant_a, roles=["student"])
    parent_user = user_in(tenant_a, roles=["parent"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        lesson = _make_lesson(branch=branch, teacher=profile)

        my_student: Any = StudentProfileFactory(user=student_user, branch=branch)
        CohortMembershipFactory(cohort=lesson.cohort, student=my_student)
        (other_student,) = _enroll(lesson.cohort, branch=branch)

        # A record for each student, both on the teacher's lesson.
        AttendanceRecordFactory(student=my_student, lesson=lesson, status=Status.PRESENT)
        AttendanceRecordFactory(student=other_student, lesson=lesson, status=Status.ABSENT)

        # Parent links to my_student.
        parent_profile = ParentProfileFactory(user=parent_user)
        GuardianFactory(parent=parent_profile, student=my_student)

        # A record on a DIFFERENT teacher's lesson — the teacher must not see it.
        other_profile = TeacherProfileFactory(branch=branch)
        foreign_lesson = _make_lesson(branch=branch, teacher=other_profile)
        foreign_student = StudentProfileFactory(branch=branch)
        CohortMembershipFactory(cohort=foreign_lesson.cohort, student=foreign_student)
        AttendanceRecordFactory(student=foreign_student, lesson=foreign_lesson, status=Status.ABSENT)

        my_student_id, foreign_lesson_id = my_student.id, foreign_lesson.id

    # Student sees only their own record.
    student_body = as_user(tenant_a, student_user).get("/api/v1/attendance/records/").json()
    assert {r["student"] for r in student_body["results"]} == {my_student_id}

    # Parent sees only the linked child's record.
    parent_body = as_user(tenant_a, parent_user).get("/api/v1/attendance/records/").json()
    assert {r["student"] for r in parent_body["results"]} == {my_student_id}

    # Teacher sees only records on lessons they teach (2 records), not the foreign one.
    teacher_body = as_user(tenant_a, teacher_user).get("/api/v1/attendance/records/").json()
    assert teacher_body["count"] == 2
    assert all(r["lesson"] != foreign_lesson_id for r in teacher_body["results"])


def test_csv_export_shape(tenant_a, user_in, as_user):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(branch=branch)
        cohort = CohortFactory(branch=branch)
        students = _enroll(cohort, n=3, branch=branch)
        for i, student in enumerate(students):
            day = _aware(2026, 4, 1 + i, 9)
            lesson = _make_lesson(
                branch=branch, teacher=profile, cohort=cohort, starts_at=day, ends_at=day + timedelta(hours=1)
            )
            AttendanceRecordFactory(student=student, lesson=lesson, status=Status.PRESENT)
        record_count = AttendanceRecord.objects.count()

    resp = as_user(tenant_a, director).get("/api/v1/attendance/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    content = b"".join(resp.streaming_content).decode()
    rows = [line for line in content.splitlines() if line]
    assert rows[0] == "date,lesson,student,status,marked_by"
    assert len(rows) == record_count + 1  # header + one row per record


def test_records_list_cross_tenant_isolated(tenant_a, tenant_b, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(branch=branch)
        lesson = _make_lesson(branch=branch, teacher=profile)
        (student,) = _enroll(lesson.cohort, branch=branch)
        AttendanceRecordFactory(student=student, lesson=lesson, status=Status.PRESENT)

    director_b = user_in(tenant_b, roles=["director"])
    body = as_user(tenant_b, director_b).get("/api/v1/attendance/records/").json()
    assert body["count"] == 0  # tenant_a's record is invisible from tenant_b


def test_mark_cross_tenant_lesson_404(tenant_a, tenant_b, user_in, as_user):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        lesson = _make_lesson(branch=branch, teacher=profile)
        lesson_id = lesson.id

    # A tenant_b teacher cannot reach tenant_a's lesson id — it does not exist there.
    teacher_b = user_in(tenant_b, roles=["teacher"])
    resp = as_user(tenant_b, teacher_b).post(
        f"/api/v1/attendance/lessons/{lesson_id}/mark/", [], format="json"
    )
    assert resp.status_code == 404


def test_records_list_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        profile = TeacherProfileFactory(branch=branch)
        cohort = CohortFactory(branch=branch)
        students = _enroll(cohort, n=5, branch=branch)
        for i, student in enumerate(students):
            day = _aware(2026, 5, 1 + i, 9)
            lesson = _make_lesson(
                branch=branch, teacher=profile, cohort=cohort, starts_at=day, ends_at=day + timedelta(hours=1)
            )
            AttendanceRecordFactory(student=student, lesson=lesson, status=Status.PRESENT)

    client = as_user(tenant_a, director)
    with django_assert_max_num_queries(8):
        body = client.get("/api/v1/attendance/records/").json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 5
