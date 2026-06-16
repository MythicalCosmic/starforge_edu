"""Schedule lane tests (D2-A): materialization, conflicts (service + DB-level
exclusion), one-off ops, iCal, scoping, query budget."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.cohorts.tests.factories import CohortFactory
from apps.org.models import BranchHoliday
from apps.org.tests.factories import BranchFactory, RoomFactory
from apps.schedule import services
from apps.schedule.models import Lesson
from apps.schedule.tests.factories import TermFactory
from apps.teachers.tests.factories import TeacherProfileFactory
from core.exceptions import ConflictException, ValidationException

pytestmark = pytest.mark.django_db


def _aware(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


def _setup(*, term_end=date(2026, 12, 31)):
    branch = BranchFactory()
    return {
        "branch": branch,
        "term": TermFactory(start_date=date(2026, 1, 1), end_date=term_end),
        "cohort": CohortFactory(branch=branch),
        "teacher": TeacherProfileFactory(branch=branch),
        "room": RoomFactory(branch=branch),
    }


def _make_rule(ctx, *, rrule="FREQ=WEEKLY;BYDAY=MO,WE", start=date(2026, 7, 6), end=date(2026, 7, 31)):
    return services.create_rule(
        term=ctx["term"],
        cohort=ctx["cohort"],
        teacher=ctx["teacher"],
        room=ctx["room"],
        title="Algebra",
        rrule=rrule,
        start_date=start,
        end_date=end,
        start_time=time(14, 0),
        end_time=time(15, 30),
    )


def test_materialize_counts_and_holiday_skip(tenant_a):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        BranchHoliday.objects.create(branch=ctx["branch"], date=date(2026, 7, 6), name="Holiday")
        rule = _make_rule(ctx)
        # Jul 6,8,13,15,20,22,27,29 = 8 Mon/Wed slots, minus the Jul 6 holiday = 7.
        assert rule.lessons.count() == 7
        assert not rule.lessons.filter(starts_at__date=date(2026, 7, 6)).exists()


def test_materialize_idempotent(tenant_a):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        rule = _make_rule(ctx)
        first = set(rule.lessons.values_list("starts_at", flat=True))
        services.materialize_rule(rule)
        second = set(rule.lessons.values_list("starts_at", flat=True))
        assert first == second
        assert rule.lessons.count() == 8


def test_detached_lesson_survives_rematerialize(tenant_a):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        rule = _make_rule(ctx)
        lesson = rule.lessons.order_by("starts_at").first()
        services.move_occurrence(lesson, starts_at=_aware(2026, 8, 3, 9), ends_at=_aware(2026, 8, 3, 10))
        services.materialize_rule(rule)
        lesson.refresh_from_db()
        assert lesson.detached_from_rule is True
        assert rule.lessons.filter(pk=lesson.pk).exists()


def test_exclusion_constraint_blocks_raw_orm_overlap(tenant_a):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        start = _aware(2026, 7, 6, 14)
        Lesson.objects.create(
            term=ctx["term"],
            cohort=ctx["cohort"],
            teacher=ctx["teacher"],
            title="A",
            starts_at=start,
            ends_at=start + timedelta(hours=1),
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Lesson.objects.create(
                term=ctx["term"],
                cohort=ctx["cohort"],
                teacher=ctx["teacher"],
                title="B",
                starts_at=start + timedelta(minutes=30),
                ends_at=start + timedelta(minutes=90),
            )


@pytest.mark.parametrize("dimension", ["teacher", "cohort", "room"])
def test_conflict_overlap_raises_409(tenant_a, dimension):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        _make_rule(ctx, rrule="FREQ=WEEKLY;BYDAY=MO", start=date(2026, 7, 6), end=date(2026, 7, 6))
        # A second rule overlapping on the chosen dimension, same Monday 14:00.
        other = dict(ctx)
        if dimension == "teacher":
            other["cohort"] = CohortFactory(branch=ctx["branch"])
            other["room"] = RoomFactory(branch=ctx["branch"])
        elif dimension == "cohort":
            other["teacher"] = TeacherProfileFactory(branch=ctx["branch"])
            other["room"] = RoomFactory(branch=ctx["branch"])
        else:  # room
            other["teacher"] = TeacherProfileFactory(branch=ctx["branch"])
            other["cohort"] = CohortFactory(branch=ctx["branch"])
        with pytest.raises(ConflictException) as exc:
            _make_rule(other, rrule="FREQ=WEEKLY;BYDAY=MO", start=date(2026, 7, 6), end=date(2026, 7, 6))
        assert exc.value.code == "schedule_conflict"
        assert dimension in (exc.value.fields or {})["conflicts"]


def test_adjacent_lessons_allowed(tenant_a):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        start = _aware(2026, 7, 6, 14)
        Lesson.objects.create(
            term=ctx["term"],
            cohort=ctx["cohort"],
            teacher=ctx["teacher"],
            title="A",
            starts_at=start,
            ends_at=start + timedelta(hours=1),
        )
        # 15:00-16:00 touches the edge — NOT a conflict.
        conflicts = services.check_conflicts(
            starts_at=start + timedelta(hours=1),
            ends_at=start + timedelta(hours=2),
            cohort_id=ctx["cohort"].id,
            teacher_id=ctx["teacher"].id,
            room_id=ctx["room"].id,
        )
        assert conflicts == {}


def test_bulk_reschedule_atomic_rollback_on_conflict(tenant_a):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        rule = _make_rule(ctx)
        # Park a fixed lesson where a +1-day shift of the first lesson would land,
        # so the shift induces a conflict and must roll the whole batch back.
        first = rule.lessons.order_by("starts_at").first()
        blocker_start = first.starts_at + timedelta(days=1)
        blocker_cohort: Any = CohortFactory(branch=ctx["branch"])
        Lesson.objects.create(
            term=ctx["term"],
            cohort=blocker_cohort,
            teacher=ctx["teacher"],
            title="Blocker",
            starts_at=blocker_start,
            ends_at=blocker_start + timedelta(hours=1),
        )
        before = list(rule.lessons.order_by("starts_at").values_list("starts_at", flat=True))
        with pytest.raises(ConflictException):
            services.bulk_reschedule(rule, shift_minutes=24 * 60)
        after = list(rule.lessons.order_by("starts_at").values_list("starts_at", flat=True))
        assert before == after  # nothing moved


def test_ical_feed_valid_and_cross_tenant_rejected(tenant_a, tenant_b, user_in):
    from icalendar import Calendar

    from core.exceptions import AuthenticationException

    user = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        _make_rule(ctx)
        token = services.ical_token_for(user)
        feed = services.build_ical(services.lessons_for_token(token))
        assert Calendar.from_ical(feed)["prodid"]
    # Same token on tenant_b → tenant_mismatch.
    with schema_context(tenant_b.schema_name):
        with pytest.raises(AuthenticationException) as exc:
            services.lessons_for_token(token)
        assert exc.value.code == "tenant_mismatch"


def test_invalid_rrule_rejected(tenant_a):
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        with pytest.raises(ValidationException) as exc:
            _make_rule(ctx, rrule="THIS-IS-NOT-AN-RRULE")
        assert exc.value.code == "invalid_rrule"


# --- API surface ---


def test_rules_create_requires_write(tenant_a, as_role):
    from core.permissions import Role

    client, _ = as_role(Role.STUDENT)
    resp = client.post("/api/v1/schedule/rules/", {}, format="json")
    assert resp.status_code == 403


def test_reminder_task_idempotent_and_schema_scoped(tenant_a):
    from apps.schedule.services import emit_due_reminders
    from apps.schedule.signals import lesson_reminder_due

    received: list[int] = []

    def _recv(sender, lesson_id, **kw):
        received.append(lesson_id)

    lesson_reminder_due.connect(_recv)
    try:
        with schema_context(tenant_a.schema_name):
            ctx = _setup()
            now = timezone.now()
            lesson = Lesson.objects.create(
                term=ctx["term"],
                cohort=ctx["cohort"],
                teacher=ctx["teacher"],
                title="Soon",
                starts_at=now + timedelta(minutes=30),
                ends_at=now + timedelta(minutes=90),
            )
            assert emit_due_reminders() == 1
            lesson.refresh_from_db()
            assert lesson.reminder_sent_at is not None
            assert emit_due_reminders() == 0  # idempotent: reminder_sent_at is the key
        assert received == [lesson.pk]
    finally:
        lesson_reminder_due.disconnect(_recv)


def test_archive_ended_term_lessons(tenant_a):
    from apps.schedule.services import archive_ended_term_lessons

    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        objs: dict[str, Any] = {
            "term": TermFactory(
                academic_year="2020-2021",
                name="Ended",
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 31),
            ),
            "cohort": CohortFactory(branch=branch),
            "teacher": TeacherProfileFactory(branch=branch),
        }
        lesson = Lesson.objects.create(
            term=objs["term"],
            cohort=objs["cohort"],
            teacher=objs["teacher"],
            title="Old",
            starts_at=_aware(2020, 3, 1, 14),
            ends_at=_aware(2020, 3, 1, 15),
        )
        assert archive_ended_term_lessons() == 1
        lesson.refresh_from_db()
        assert lesson.status == Lesson.Status.ARCHIVED


def test_lessons_list_query_budget(tenant_a, as_role, django_assert_max_num_queries):
    from core.permissions import Role

    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        ctx = _setup()
        _make_rule(ctx)
        _make_rule(_setup())
    with django_assert_max_num_queries(8):
        body = client.get("/api/v1/schedule/lessons/").json()
    assert set(body) == {"count", "next", "previous", "results"}
