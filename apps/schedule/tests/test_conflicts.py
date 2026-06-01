"""Schedule conflict detection + recurring generation — the high-risk logic."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.cohorts.models import Cohort
from apps.org.models import Branch, Room
from apps.schedule.models import Holiday, Lesson
from apps.schedule.services import create_recurring, find_conflicts
from apps.teachers.models import TeacherProfile
from apps.users.models import RoleMembership, User
from core.permissions import Role


def dt(day: int, hour: int, minute: int = 0) -> datetime:
    return timezone.make_aware(datetime(2026, 6, day, hour, minute))


class ScheduleConflictTest(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Test Center"
        tenant.slug = "test"

    def setUp(self):
        self.branch = Branch.objects.create(name="Main", slug="main")
        self.room1 = Room.objects.create(branch=self.branch, name="101")
        self.room2 = Room.objects.create(branch=self.branch, name="102")
        self.teacher1 = TeacherProfile.objects.create(user=User.objects.create(phone="+998900000101"))
        self.teacher2 = TeacherProfile.objects.create(user=User.objects.create(phone="+998900000102"))
        self.cohort1 = Cohort.objects.create(branch=self.branch, name="A")
        self.cohort2 = Cohort.objects.create(branch=self.branch, name="B")

    def _lesson(self, **kw):
        defaults = dict(
            cohort=self.cohort1, room=self.room1, teacher=self.teacher1, start=dt(8, 10), end=dt(8, 11)
        )
        defaults.update(kw)
        return Lesson.objects.create(**defaults)

    # -- conflict matrix ----------------------------------------------------

    def test_room_clash(self):
        self._lesson()
        hits = find_conflicts(
            start=dt(8, 10, 30),
            end=dt(8, 11, 30),
            room=self.room1,
            teacher=self.teacher2,
            cohort=self.cohort2,
        )
        assert hits.count() == 1

    def test_teacher_clash(self):
        self._lesson()
        hits = find_conflicts(
            start=dt(8, 10, 30),
            end=dt(8, 11, 30),
            room=self.room2,
            teacher=self.teacher1,
            cohort=self.cohort2,
        )
        assert hits.count() == 1

    def test_cohort_clash(self):
        self._lesson()
        hits = find_conflicts(
            start=dt(8, 10, 30),
            end=dt(8, 11, 30),
            room=self.room2,
            teacher=self.teacher2,
            cohort=self.cohort1,
        )
        assert hits.count() == 1

    def test_no_clash_when_times_only_touch(self):
        self._lesson()  # 10:00-11:00
        hits = find_conflicts(
            start=dt(8, 11), end=dt(8, 12), room=self.room1, teacher=self.teacher1, cohort=self.cohort1
        )
        assert hits.count() == 0

    def test_no_clash_when_all_resources_differ(self):
        self._lesson()
        hits = find_conflicts(
            start=dt(8, 10, 30),
            end=dt(8, 11, 30),
            room=self.room2,
            teacher=self.teacher2,
            cohort=self.cohort2,
        )
        assert hits.count() == 0

    def test_cancelled_lesson_frees_the_slot(self):
        self._lesson(status=Lesson.Status.CANCELLED)
        hits = find_conflicts(start=dt(8, 10, 30), end=dt(8, 11, 30), room=self.room1)
        assert hits.count() == 0

    # -- recurring ----------------------------------------------------------

    def test_recurring_generates_and_skips_holiday(self):
        # 2026-06-01 is a Monday. Mon+Wed across 06-01..06-10 = 4 slots.
        Holiday.objects.create(branch=self.branch, date=dt(3, 0).date(), name="Holiday")  # a Wednesday
        created, skipped = create_recurring(
            cohort=self.cohort1,
            room=self.room1,
            teacher=self.teacher1,
            start_time=dt(1, 14).time(),
            end_time=dt(1, 15).time(),
            weekdays=[0, 2],
            start_date=dt(1, 0).date(),
            end_date=dt(10, 0).date(),
        )
        assert len(created) == 3  # 4 slots minus the holiday Wednesday
        assert skipped == []  # holidays are omitted, not reported as conflicts
        assert all(lsn.series_id == created[0].series_id for lsn in created)

    def test_recurring_skips_conflicting_slot(self):
        # Pre-existing lesson on Mon 06-08 14:00 blocks that occurrence (same room).
        self._lesson(start=dt(8, 14), end=dt(8, 15))
        created, skipped = create_recurring(
            cohort=self.cohort2,
            room=self.room1,
            teacher=self.teacher2,
            start_time=dt(1, 14).time(),
            end_time=dt(1, 15).time(),
            weekdays=[0],  # Mondays: 06-01, 06-08
            start_date=dt(1, 0).date(),
            end_date=dt(8, 0).date(),
        )
        assert len(created) == 1  # 06-01 ok, 06-08 conflicts
        assert len(skipped) == 1 and skipped[0]["reason"] == "conflict"

    # -- API ----------------------------------------------------------------

    def test_api_rejects_conflicting_lesson(self):
        self._lesson()
        director = User.objects.create(phone="+998900000200")
        RoleMembership.objects.create(user=director, branch=self.branch, role=Role.DIRECTOR)
        client = APIClient()
        client.force_authenticate(user=director)
        r = client.post(
            "/api/v1/schedule/lessons/",
            {
                "cohort": self.cohort1.id,
                "room": self.room1.id,
                "teacher": self.teacher1.id,
                "start": dt(8, 10, 30).isoformat(),
                "end": dt(8, 11, 30).isoformat(),
            },
            format="json",
            HTTP_HOST=self.get_test_tenant_domain(),
        )
        assert r.status_code == 400, r.content
        # core.exceptions wraps DRF errors as {"error": {"code", "detail": {...}}}.
        assert "conflict" in r.json()["error"]["detail"]
