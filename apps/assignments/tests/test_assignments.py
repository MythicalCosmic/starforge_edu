"""Assignments lane tests (D2-D): late-flag grace, resubmit limit, rubric
validation, draft/cross-cohort scoping, due-soon idempotency, the four signals,
upload-url allowlist + key prefix, plagiarism stub, cross-tenant, query budgets."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import time_machine
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.assignments import selectors, services
from apps.assignments.models import Assignment
from apps.assignments.services import PlagiarismResult
from apps.assignments.signals import (
    ai_feedback_requested,
    assignment_due_soon,
    assignment_published,
    submission_graded,
)
from apps.assignments.tests.factories import AssignmentFactory
from apps.cohorts.tests.factories import CohortFactory, CohortMembershipFactory
from apps.org.models import CenterSettings
from apps.org.tests.factories import BranchFactory
from apps.students.tests.factories import StudentProfileFactory
from apps.teachers.tests.factories import TeacherProfileFactory
from core.exceptions import UnprocessableEntity

pytestmark = pytest.mark.django_db


def _aware(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


def _set_knob(**kwargs) -> None:
    from django.core.cache import cache

    settings = CenterSettings.load()
    for key, value in kwargs.items():
        setattr(settings, key, value)
    settings.save(update_fields=list(kwargs))
    cache.clear()


def _member(cohort, branch) -> Any:
    student = StudentProfileFactory(branch=branch)
    CohortMembershipFactory(cohort=cohort, student=student)
    return student


# --------------------------------------------------------------------------- #
# late flag + resubmit limit (knob-driven)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("offset_min", "expected_late"), [(29, False), (30, False), (31, True)])
def test_late_flag_boundaries_with_grace(tenant_a, offset_min, expected_late):
    with schema_context(tenant_a.schema_name):
        _set_knob(assignment_grace_minutes=30)
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        due = _aware(2026, 6, 1, 12)
        assignment: Any = AssignmentFactory(cohort=cohort, due_at=due)
        student = _member(cohort, branch)
        with time_machine.travel(due + timedelta(minutes=offset_min), tick=False):
            submission = services.submit(assignment=assignment, student=student)
        assert submission.is_late is expected_late


def test_resubmit_limit_default_and_per_assignment_override(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)

        # Default knob = 2 → 3 attempts allowed, 4th rejected.
        default_assignment: Any = AssignmentFactory(cohort=cohort)
        student = _member(cohort, branch)
        for _ in range(3):
            services.submit(assignment=default_assignment, student=student)
        with pytest.raises(UnprocessableEntity) as exc:
            services.submit(assignment=default_assignment, student=student)
        assert exc.value.code == "resubmit_limit_exceeded"

        # Per-assignment override = 0 → only the original attempt.
        strict: Any = AssignmentFactory(cohort=cohort, max_resubmits=0)
        other = _member(cohort, branch)
        services.submit(assignment=strict, student=other)
        with pytest.raises(UnprocessableEntity) as exc2:
            services.submit(assignment=strict, student=other)
        assert exc2.value.code == "resubmit_limit_exceeded"


def test_submit_rejects_closed_and_non_member(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        closed: Any = AssignmentFactory(cohort=cohort, status=Assignment.Status.CLOSED)
        member = _member(cohort, branch)
        with pytest.raises(UnprocessableEntity) as exc:
            services.submit(assignment=closed, student=member)
        assert exc.value.code == "assignment_closed"

        published: Any = AssignmentFactory(cohort=cohort)
        outsider: Any = StudentProfileFactory(branch=branch)  # no membership
        with pytest.raises(UnprocessableEntity) as exc2:
            services.submit(assignment=published, student=outsider)
        assert exc2.value.code == "student_not_in_cohort"


# --------------------------------------------------------------------------- #
# rubric validation
# --------------------------------------------------------------------------- #


def test_rubric_validation_unknown_criterion_and_sum_cap(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        student = _member(cohort, branch)

        ok_rubric: Any = AssignmentFactory(
            cohort=cohort,
            max_score=Decimal("100"),
            rubric=[{"criterion": "clarity", "max_points": 50}, {"criterion": "depth", "max_points": 50}],
        )
        sub = services.submit(assignment=ok_rubric, student=student)
        with pytest.raises(UnprocessableEntity) as exc:
            services.grade_submission(
                submission=sub, score=Decimal("80"), rubric_scores=[{"criterion": "nope", "points": 10}]
            )
        assert exc.value.code == "unknown_rubric_criterion"

        # Rubric whose Σ max_points exceeds the assignment max_score.
        over: Any = AssignmentFactory(
            cohort=cohort,
            max_score=Decimal("100"),
            rubric=[{"criterion": "a", "max_points": 70}, {"criterion": "b", "max_points": 70}],
        )
        sub2 = services.submit(assignment=over, student=_member(cohort, branch))
        with pytest.raises(UnprocessableEntity) as exc2:
            services.grade_submission(submission=sub2, score=Decimal("90"), rubric_scores=[])
        assert exc2.value.code == "rubric_exceeds_max_score"


def test_grade_score_out_of_range(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        student = _member(cohort, branch)
        assignment: Any = AssignmentFactory(cohort=cohort, max_score=Decimal("100"))
        sub = services.submit(assignment=assignment, student=student)
        with pytest.raises(UnprocessableEntity) as exc:
            services.grade_submission(submission=sub, score=Decimal("101"))
        assert exc.value.code == "score_out_of_range"


# --------------------------------------------------------------------------- #
# plagiarism stub
# --------------------------------------------------------------------------- #


def test_plagiarism_stub_typed(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        student = _member(cohort, branch)
        assignment: Any = AssignmentFactory(cohort=cohort)
        sub = services.submit(assignment=assignment, student=student)
        result = services.check_submission(sub)
        assert isinstance(result, PlagiarismResult)
        assert (result.status, result.score) == ("not_implemented", None)


# --------------------------------------------------------------------------- #
# upload-url
# --------------------------------------------------------------------------- #


def test_upload_url_key_prefix_and_allowlist(tenant_a, monkeypatch):
    monkeypatch.setattr(services, "presign_upload", lambda key, content_type="": f"https://s3/{key}")
    with schema_context(tenant_a.schema_name):
        result = services.validate_and_presign_upload(
            filename="essay.pdf", content_type="application/pdf", size_bytes=1024
        )
        assert result["key"].startswith(f"{tenant_a.schema_name}/assignments/")
        assert result["key"].endswith("/essay.pdf")

        with pytest.raises(UnprocessableEntity) as exc:
            services.validate_and_presign_upload(
                filename="virus.exe", content_type="application/octet-stream", size_bytes=10
            )
        assert exc.value.code == "file_type_not_allowed"

        with pytest.raises(UnprocessableEntity) as exc2:
            services.validate_and_presign_upload(
                filename="big.pdf", content_type="application/pdf", size_bytes=10**12
            )
        assert exc2.value.code == "file_too_large"


# --------------------------------------------------------------------------- #
# due-soon task + signals
# --------------------------------------------------------------------------- #


def test_due_soon_task_idempotent(tenant_a):
    received: list[int] = []

    def _recv(sender, assignment_id, **kw):
        received.append(assignment_id)

    assignment_due_soon.connect(_recv)
    try:
        with schema_context(tenant_a.schema_name):
            branch = BranchFactory()
            cohort = CohortFactory(branch=branch)
            AssignmentFactory(cohort=cohort, due_at=timezone.now() + timedelta(hours=12))
            assert services.emit_due_soon_reminders() == 1
            assert services.emit_due_soon_reminders() == 0  # stamped → idempotent
        assert len(received) == 1
    finally:
        assignment_due_soon.disconnect(_recv)


def test_all_four_signals_emitted(tenant_a, user_in, django_capture_on_commit_callbacks):
    seen: set[str] = set()
    receivers = {
        "published": (assignment_published, lambda **k: seen.add("published")),
        "due_soon": (assignment_due_soon, lambda **k: seen.add("due_soon")),
        "graded": (submission_graded, lambda **k: seen.add("graded")),
        "ai": (ai_feedback_requested, lambda **k: seen.add("ai")),
    }
    for signal, fn in receivers.values():
        signal.connect(fn)
    try:
        teacher_user = user_in(tenant_a, roles=["teacher"])
        with schema_context(tenant_a.schema_name):
            branch = BranchFactory()
            teacher_profile = TeacherProfileFactory(user=teacher_user, branch=branch)
            cohort = CohortFactory(branch=branch, primary_teacher=teacher_profile)
            student = _member(cohort, branch)

            draft: Any = AssignmentFactory(
                cohort=cohort, status=Assignment.Status.DRAFT, due_at=timezone.now() + timedelta(hours=10)
            )
            with django_capture_on_commit_callbacks(execute=True):
                services.publish_assignment(assignment=draft, actor=teacher_user)
            services.emit_due_soon_reminders()

            sub = services.submit(assignment=draft, student=student)
            with django_capture_on_commit_callbacks(execute=True):
                services.grade_submission(submission=sub, score=Decimal("90"))
            services.request_ai_feedback(submission=sub, requested_by=teacher_user)

        assert seen == {"published", "due_soon", "graded", "ai"}
    finally:
        for signal, fn in receivers.values():
            signal.disconnect(fn)


# --------------------------------------------------------------------------- #
# scoping (drafts, cross-cohort) via the API
# --------------------------------------------------------------------------- #


def test_draft_invisible_to_students(tenant_a, user_in, as_user):
    student_user = user_in(tenant_a, roles=["student"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        student = StudentProfileFactory(user=student_user, branch=branch)
        CohortMembershipFactory(cohort=cohort, student=student)
        published: Any = AssignmentFactory(cohort=cohort, status=Assignment.Status.PUBLISHED)
        draft: Any = AssignmentFactory(cohort=cohort, status=Assignment.Status.DRAFT)
        published_id, draft_id = published.id, draft.id

    client = as_user(tenant_a, student_user)
    body = client.get("/api/v1/assignments/").json()
    assert {a["id"] for a in body["results"]} == {published_id}
    assert client.get(f"/api/v1/assignments/{draft_id}/").status_code == 404


def test_cross_cohort_submit_404(tenant_a, user_in, as_user):
    student_user = user_in(tenant_a, roles=["student"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        my_cohort = CohortFactory(branch=branch)
        other_cohort = CohortFactory(branch=branch)
        student = StudentProfileFactory(user=student_user, branch=branch)
        CohortMembershipFactory(cohort=my_cohort, student=student)
        foreign: Any = AssignmentFactory(cohort=other_cohort, status=Assignment.Status.PUBLISHED)
        foreign_id = foreign.id

    resp = as_user(tenant_a, student_user).post(
        f"/api/v1/assignments/{foreign_id}/submissions/", {"text": "hi"}, format="json"
    )
    assert resp.status_code == 404  # scoped out, not a 403 existence leak


def test_student_submits_own_cohort_201(tenant_a, user_in, as_user):
    student_user = user_in(tenant_a, roles=["student"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        student = StudentProfileFactory(user=student_user, branch=branch)
        CohortMembershipFactory(cohort=cohort, student=student)
        assignment: Any = AssignmentFactory(cohort=cohort, status=Assignment.Status.PUBLISHED)
        assignment_id = assignment.id

    resp = as_user(tenant_a, student_user).post(
        f"/api/v1/assignments/{assignment_id}/submissions/", {"text": "my answer"}, format="json"
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["attempt_number"] == 1
    assert body["status"] == "submitted"


def test_assignment_create_requires_write(tenant_a, as_role):
    from core.permissions import Role

    client, _ = as_role(Role.STUDENT)
    resp = client.post("/api/v1/assignments/", {}, format="json")
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# cross-tenant + query budgets
# --------------------------------------------------------------------------- #


def test_assignments_cross_tenant_isolated(tenant_a, tenant_b, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        AssignmentFactory(cohort=cohort, status=Assignment.Status.PUBLISHED)

    director_b = user_in(tenant_b, roles=["director"])
    body = as_user(tenant_b, director_b).get("/api/v1/assignments/").json()
    assert body["count"] == 0


def test_assignments_list_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        for _ in range(5):
            AssignmentFactory(cohort=cohort, status=Assignment.Status.PUBLISHED)

    client = as_user(tenant_a, director)
    with django_assert_max_num_queries(8):
        body = client.get("/api/v1/assignments/").json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 5


def test_submissions_list_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        teacher_profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        cohort = CohortFactory(branch=branch, primary_teacher=teacher_profile)
        assignment: Any = AssignmentFactory(cohort=cohort, status=Assignment.Status.PUBLISHED)
        for _ in range(5):
            student = _member(cohort, branch)
            services.submit(assignment=assignment, student=student)
        assignment_id = assignment.id

    client = as_user(tenant_a, teacher_user)
    with django_assert_max_num_queries(8):
        resp = client.get(f"/api/v1/assignments/{assignment_id}/submissions/")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_scoped_assignments_helper(tenant_a, user_in):
    """Direct selector check — teacher sees own cohort incl. drafts."""
    teacher_user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        teacher_profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        cohort = CohortFactory(branch=branch, primary_teacher=teacher_profile)
        AssignmentFactory(cohort=cohort, status=Assignment.Status.DRAFT)
        AssignmentFactory(cohort=cohort, status=Assignment.Status.PUBLISHED)
        # An unrelated cohort's assignment must not appear.
        AssignmentFactory(cohort=CohortFactory(branch=branch), status=Assignment.Status.PUBLISHED)
        qs = selectors.scoped_assignments(user=teacher_user, roles={"teacher"})
        assert qs.count() == 2
