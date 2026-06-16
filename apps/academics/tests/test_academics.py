"""Academics lane tests (D2-C): weighted grade math + scheme display, CSV import
atomicity, publication gating, transcript task lifecycle, the grade-changed
signal, honor-roll knob, scoping, cross-tenant, and query budgets."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django_tenants.utils import schema_context

from apps.academics import selectors, services
from apps.academics.grading import display_for
from apps.academics.models import ExamResult, Transcript
from apps.academics.signals import grade_changed
from apps.academics.tests.factories import ExamFactory, GradeFactory, SubjectFactory
from apps.cohorts.tests.factories import CohortFactory, CohortMembershipFactory
from apps.org.models import CenterSettings
from apps.org.tests.factories import BranchFactory
from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
from apps.schedule.tests.factories import TermFactory
from apps.students.tests.factories import StudentProfileFactory
from apps.teachers.tests.factories import TeacherProfileFactory
from core.exceptions import UnprocessableEntity

pytestmark = pytest.mark.django_db


def _set_scheme(scheme: str) -> None:
    from django.core.cache import cache

    settings = CenterSettings.load()
    settings.grading_scheme = scheme
    settings.save(update_fields=["grading_scheme"])
    cache.clear()


def _three_weighted_exams(*, subject, cohort, term, student, scores, weights, published=(True, True, True)):
    """Create 3 published-by-default exams (max 100) with `weights` and record
    `scores` for `student`. Returns the exams."""
    exams = []
    for i, (score, weight, pub) in enumerate(zip(scores, weights, published, strict=True)):
        exam: Any = ExamFactory(
            subject=subject,
            cohort=cohort,
            term=term,
            title=f"E{i}",
            max_score=Decimal("100"),
            weight=Decimal(weight),
            is_published=pub,
        )
        ExamResult.objects.create(exam=exam, student=student, score=Decimal(score))
        exams.append(exam)
    return exams


# --------------------------------------------------------------------------- #
# grade math + display scheme
# --------------------------------------------------------------------------- #


def test_weighted_term_grade_fixture(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        subject = SubjectFactory()
        cohort = CohortFactory(branch=branch)
        term: Any = TermFactory()
        student: Any = StudentProfileFactory(branch=branch)
        # weights .2/.3/.5, scores 90/80/100 → 100*(.18+.24+.50) = 92.000
        _three_weighted_exams(
            subject=subject,
            cohort=cohort,
            term=term,
            student=student,
            scores=("90", "80", "100"),
            weights=(".2", ".3", ".5"),
        )
        grade = services.compute_term_grade(student=student, subject=subject, term=term)
        assert grade is not None
        assert grade.value_raw == Decimal("92.000")
        assert grade.value_display == "92.0"
        assert len(grade.components) == 3


def test_unpublished_exam_excluded(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        subject = SubjectFactory()
        cohort = CohortFactory(branch=branch)
        term: Any = TermFactory()
        student: Any = StudentProfileFactory(branch=branch)
        # 3rd exam (the 100, weight .5) is UNPUBLISHED → drops out. Remaining
        # weights .2/.3 → 100*(.18+.24)/.5 = 84.000.
        _three_weighted_exams(
            subject=subject,
            cohort=cohort,
            term=term,
            student=student,
            scores=("90", "80", "100"),
            weights=(".2", ".3", ".5"),
            published=(True, True, False),
        )
        grade = services.compute_term_grade(student=student, subject=subject, term=term)
        assert grade is not None
        assert grade.value_raw == Decimal("84.000")
        assert len(grade.components) == 2


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [("percentage", "92.0"), ("letter", "A"), ("gpa", "3.68")],
)
def test_value_display_percentage_letter_gpa(tenant_a, scheme, expected):
    with schema_context(tenant_a.schema_name):
        _set_scheme(scheme)
        branch = BranchFactory()
        subject = SubjectFactory()
        cohort = CohortFactory(branch=branch)
        term: Any = TermFactory()
        student: Any = StudentProfileFactory(branch=branch)
        _three_weighted_exams(
            subject=subject,
            cohort=cohort,
            term=term,
            student=student,
            scores=("90", "80", "100"),
            weights=(".2", ".3", ".5"),
        )
        grade = services.compute_term_grade(student=student, subject=subject, term=term)
        assert grade is not None
        assert grade.value_display == expected


def test_display_for_letter_bands_pure():
    assert display_for(Decimal("90"), "letter") == "A"
    assert display_for(Decimal("89.99"), "letter") == "B"
    assert display_for(Decimal("60"), "letter") == "D"
    assert display_for(Decimal("59.9"), "letter") == "F"


# --------------------------------------------------------------------------- #
# exam results — validation + grade_changed signal
# --------------------------------------------------------------------------- #


def test_record_results_score_out_of_range_422(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        exam: Any = ExamFactory(max_score=Decimal("100"))
        student: Any = StudentProfileFactory(branch=branch)
        with pytest.raises(UnprocessableEntity) as exc:
            services.record_results(
                exam=exam, rows=[{"student": student, "score": Decimal("101")}], actor=None
            )
        assert exc.value.code == "score_out_of_range"
        assert "0" in (exc.value.fields or {})


def test_grade_changed_emitted_once_on_overwrite(tenant_a, django_capture_on_commit_callbacks):
    received: list[dict] = []

    def _recv(sender, **kwargs):
        received.append(kwargs)

    grade_changed.connect(_recv)
    try:
        with schema_context(tenant_a.schema_name):
            branch = BranchFactory()
            exam: Any = ExamFactory(max_score=Decimal("100"))
            student: Any = StudentProfileFactory(branch=branch)

            with django_capture_on_commit_callbacks(execute=True):
                services.record_results(
                    exam=exam, rows=[{"student": student, "score": Decimal("70")}], actor=None
                )
            assert received == []  # first entry does NOT emit

            with django_capture_on_commit_callbacks(execute=True):
                services.record_results(
                    exam=exam, rows=[{"student": student, "score": Decimal("88")}], actor=None
                )
            assert len(received) == 1  # overwrite emits exactly once
            assert received[0]["old_score"] == Decimal("70")
            assert received[0]["new_score"] == Decimal("88")
    finally:
        grade_changed.disconnect(_recv)


# --------------------------------------------------------------------------- #
# CSV import
# --------------------------------------------------------------------------- #


def test_csv_import_atomic_and_row_errors(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        exam: Any = ExamFactory(max_score=Decimal("100"))
        s1: Any = StudentProfileFactory(branch=branch)
        s2: Any = StudentProfileFactory(branch=branch)

        # One unknown student_id + one out-of-range score → 422, zero written.
        bad = io.BytesIO(
            f"student_id,score,note\n{s1.student_id},80,ok\nNOPE-99999,75,\n{s2.student_id},150,\n".encode()
        )
        bad.name = "bad.csv"
        with pytest.raises(UnprocessableEntity) as exc:
            services.bulk_grade_import(exam=exam, csv_file=bad, actor=None)
        assert exc.value.code == "csv_row_errors"
        bad_rows = {e["row"] for e in (exc.value.fields or {})["rows"]}
        assert bad_rows == {3, 4}  # header is line 1
        assert ExamResult.objects.filter(exam=exam).count() == 0

        # Clean CSV → all rows imported.
        good = io.BytesIO(f"student_id,score\n{s1.student_id},80\n{s2.student_id},90\n".encode())
        good.name = "good.csv"
        result = services.bulk_grade_import(exam=exam, csv_file=good, actor=None)
        assert result["created"] == 2
        assert ExamResult.objects.filter(exam=exam).count() == 2


# --------------------------------------------------------------------------- #
# transcript task lifecycle
# --------------------------------------------------------------------------- #


def test_transcript_task_lifecycle_idempotent(tenant_a, monkeypatch):
    uploads: list[tuple[str, bytes]] = []

    def fake_render(transcript):
        return b"%PDF-1.5\nfake transcript bytes"

    def fake_upload(key, data, *, content_type="application/octet-stream"):
        uploads.append((key, data))
        return key

    monkeypatch.setattr(services, "render_transcript_pdf", fake_render)
    monkeypatch.setattr(services, "upload_bytes", fake_upload)

    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        student: Any = StudentProfileFactory(branch=branch)
        transcript: Any = Transcript.objects.create(student=student)

        key = services.generate_transcript(transcript.id)
        transcript.refresh_from_db()
        assert transcript.status == Transcript.Status.DONE
        assert key == f"{tenant_a.schema_name}/transcripts/{transcript.id}.pdf"
        assert transcript.pdf_key == key
        assert uploads[0][1].startswith(b"%PDF")

        # Re-run is idempotent: done short-circuits, no second upload.
        services.generate_transcript(transcript.id)
        assert len(uploads) == 1


def test_transcript_post_returns_202_pending(tenant_a, user_in, as_user):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        student: Any = StudentProfileFactory(branch=branch)
        student_id = student.id

    resp = as_user(tenant_a, director).post(
        "/api/v1/academics/transcripts/", {"student": student_id}, format="json"
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    with schema_context(tenant_a.schema_name):
        assert Transcript.objects.filter(pk=body["id"], status="pending").exists()


# weasyprint needs GTK native libs (cairo/pango) absent on the Windows dev box;
# this runs the REAL renderer on CI/Linux and skips locally.
try:  # pragma: no cover - import probe
    import weasyprint  # noqa: F401

    _HAS_WEASYPRINT = True
except Exception:  # OSError too when native libs are missing
    _HAS_WEASYPRINT = False


@pytest.mark.skipif(not _HAS_WEASYPRINT, reason="weasyprint native libs unavailable (CI/Linux runs it)")
def test_weasyprint_renders_real_pdf(tenant_a):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        student: Any = StudentProfileFactory(branch=branch)
        transcript: Any = Transcript.objects.create(student=student)
        pdf = services.render_transcript_pdf(transcript)
        assert pdf.startswith(b"%PDF")


# --------------------------------------------------------------------------- #
# publication gating + scoping
# --------------------------------------------------------------------------- #


def test_publication_gating_parent_student_teacher(tenant_a, user_in, as_user):
    teacher_user = user_in(tenant_a, roles=["teacher"])
    student_user = user_in(tenant_a, roles=["student"])
    parent_user = user_in(tenant_a, roles=["parent"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        teacher_profile = TeacherProfileFactory(user=teacher_user, branch=branch)
        cohort = CohortFactory(branch=branch, primary_teacher=teacher_profile)
        subject = SubjectFactory()
        term = TermFactory()

        my_student: Any = StudentProfileFactory(user=student_user, branch=branch)
        CohortMembershipFactory(cohort=cohort, student=my_student)
        parent_profile = ParentProfileFactory(user=parent_user)
        GuardianFactory(parent=parent_profile, student=my_student)

        published: Any = GradeFactory(
            student=my_student, subject=subject, term=term, is_published=True, value_display="A"
        )
        draft: Any = GradeFactory(
            student=my_student,
            subject=SubjectFactory(),
            term=term,
            is_published=False,
            value_display="B",
        )

        # A different student's published grade — must never be visible to ours.
        other: Any = StudentProfileFactory(branch=branch)
        CohortMembershipFactory(cohort=cohort, student=other)
        GradeFactory(student=other, subject=subject, term=term, is_published=True)
        published_id, draft_id = published.id, draft.id

    student_body = as_user(tenant_a, student_user).get("/api/v1/academics/grades/").json()
    assert {g["id"] for g in student_body["results"]} == {published_id}

    parent_body = as_user(tenant_a, parent_user).get("/api/v1/academics/grades/").json()
    assert {g["id"] for g in parent_body["results"]} == {published_id}

    # Teacher of the cohort sees BOTH published + draft for their students.
    teacher_body = as_user(tenant_a, teacher_user).get("/api/v1/academics/grades/").json()
    teacher_ids = {g["id"] for g in teacher_body["results"]}
    assert published_id in teacher_ids
    assert draft_id in teacher_ids


def test_teacher_grade_read_allowed_matrix(tenant_a, as_role):
    """Day-1 asymmetry fix: TEACHER now has academics:read (D2-C-7)."""
    from core.permissions import Role

    client, _ = as_role(Role.TEACHER)
    resp = client.get("/api/v1/academics/grades/")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# honor roll knob
# --------------------------------------------------------------------------- #


def test_honor_roll_knob_flip(tenant_a):
    from django.core.cache import cache

    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        term: Any = TermFactory()
        student: Any = StudentProfileFactory(branch=branch)
        GradeFactory(
            student=student,
            subject=SubjectFactory(),
            term=term,
            value_raw=Decimal("92"),
            is_published=True,
        )

        assert selectors.honor_roll(term_id=term.id).count() == 1  # default min 90

        settings = CenterSettings.load()
        settings.honor_roll_min = Decimal("95")
        settings.save(update_fields=["honor_roll_min"])
        cache.clear()
        assert selectors.honor_roll(term_id=term.id).count() == 0  # 92 < 95


def test_honor_roll_endpoint_staff_only(tenant_a, user_in, as_user):
    student_user = user_in(tenant_a, roles=["student"])
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        term: Any = TermFactory()
        term_id = term.id

    # Student holds academics:read but honor roll is staff-only.
    student_resp = as_user(tenant_a, student_user).get(f"/api/v1/academics/honor-roll/?term={term_id}")
    assert student_resp.status_code == 403
    director_resp = as_user(tenant_a, director).get(f"/api/v1/academics/honor-roll/?term={term_id}")
    assert director_resp.status_code == 200


# --------------------------------------------------------------------------- #
# API gating, cross-tenant, query budgets
# --------------------------------------------------------------------------- #


def test_exam_create_requires_write(tenant_a, as_role):
    from core.permissions import Role

    client, _ = as_role(Role.STUDENT)
    resp = client.post("/api/v1/academics/exams/", {}, format="json")
    assert resp.status_code == 403


def test_grades_cross_tenant_isolated(tenant_a, tenant_b, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        student: Any = StudentProfileFactory(branch=branch)
        GradeFactory(student=student, subject=SubjectFactory(), term=TermFactory(), is_published=True)

    director_b = user_in(tenant_b, roles=["director"])
    body = as_user(tenant_b, director_b).get("/api/v1/academics/grades/").json()
    assert body["count"] == 0


def test_grades_list_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        term = TermFactory()
        for _ in range(5):
            student = StudentProfileFactory(branch=branch)
            GradeFactory(student=student, subject=SubjectFactory(), term=term, is_published=True)

    client = as_user(tenant_a, director)
    with django_assert_max_num_queries(8):
        body = client.get("/api/v1/academics/grades/").json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 5


def test_exams_list_query_budget(tenant_a, user_in, as_user, django_assert_max_num_queries):
    director = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
        cohort = CohortFactory(branch=branch)
        term = TermFactory()
        for i in range(5):
            ExamFactory(
                subject=SubjectFactory(),
                cohort=cohort,
                term=term,
                title=f"E{i}",
                exam_date=date(2026, 3, 1 + i),
            )

    client = as_user(tenant_a, director)
    with django_assert_max_num_queries(8):
        body = client.get("/api/v1/academics/exams/").json()
    assert body["count"] == 5
