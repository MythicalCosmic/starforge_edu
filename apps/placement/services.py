"""Placement engine services (F1-2 / F1-4): build → submit → approve / reject.

All writes are keyword-only and `@transaction.atomic`. Questions can only change
while the test is DRAFT (editing a live test would invalidate attempts already
graded against it). The approve transition locks the row (`select_for_update`) so
the state check + maker-checker self-check are race-free.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.placement.models import PlacementAnswer, PlacementAttempt, PlacementQuestion, PlacementTest
from apps.students.models import StudentProfile
from core.exceptions import (
    ConflictException,
    PermissionException,
    UnprocessableEntity,
    ValidationException,
)

_QT = PlacementQuestion.QuestionType
# Placement is an intake tool: only prospective students get a test, so submit's
# academic_level write never clobbers an enrolled student's curated level.
_PROSPECTIVE_STATUSES = (
    StudentProfile.Status.LEAD,
    StudentProfile.Status.APPLICATION,
    StudentProfile.Status.ACCEPTED,
)


@transaction.atomic
def create_test(*, title: str, created_by=None, **kwargs) -> PlacementTest:
    return PlacementTest.objects.create(title=title, created_by=created_by, **kwargs)


@transaction.atomic
def update_test(*, test: PlacementTest, **changes) -> PlacementTest:
    """Edit test metadata. Draft-only — a test that is pending or live is frozen."""
    if test.status != PlacementTest.Status.DRAFT:
        raise UnprocessableEntity(_("Only a draft test can be edited."), code="test_not_draft")
    allowed = {"title", "description", "subject"}
    for key, value in changes.items():
        if key in allowed:
            setattr(test, key, value)
    test.save()
    return test


def _validate_question(question_type: str, options: Any, correct_answer: Any) -> None:
    """Enforce a coherent answer-key per type; raise ValidationException otherwise."""
    if not isinstance(options, list):
        # The serializer JSONField accepts any JSON; a scalar/string/dict here would
        # otherwise 500 on len() or silently "match" correct_answer by substring/key.
        raise ValidationException(_("Options must be a list."), code="invalid_options")
    if question_type == _QT.SINGLE_CHOICE:
        if len(options) < 2:
            raise ValidationException(
                _("A single-choice question needs at least two options."), code="choice_needs_options"
            )
        if any(not isinstance(o, str) or not o.strip() for o in options):
            raise ValidationException(_("Options must be non-empty text."), code="invalid_options")
        if len(set(options)) != len(options):
            raise ValidationException(_("Options must be unique."), code="duplicate_options")
        if correct_answer not in options:
            raise ValidationException(
                _("The correct answer must be one of the options."), code="answer_not_in_options"
            )
    elif question_type == _QT.TRUE_FALSE:
        if not isinstance(correct_answer, bool):
            raise ValidationException(
                _("A true/false question's answer must be true or false."), code="answer_not_boolean"
            )
    elif question_type == _QT.WRITING:
        if correct_answer is not None:
            raise ValidationException(
                _("A writing question is marked by a person and has no answer key."),
                code="writing_has_no_answer",
            )


@transaction.atomic
def add_question(
    *,
    test: PlacementTest,
    prompt: str,
    question_type: str,
    options: list[Any] | None = None,
    correct_answer: Any = None,
    points: int = 1,
    order: int | None = None,
) -> PlacementQuestion:
    """Append a question. Only a DRAFT test can be edited. The parent row is locked
    so the status check and the next-slot `order` computation are race-free (two
    concurrent appends can't read the same MAX(order) and collide)."""
    test = PlacementTest.objects.select_for_update().get(pk=test.pk)
    if test.status != PlacementTest.Status.DRAFT:
        raise UnprocessableEntity(_("Only a draft test can be edited."), code="test_not_draft")
    options = options if options is not None else []
    _validate_question(question_type, options, correct_answer)
    if order is None:
        last = test.questions.order_by("-order").first()
        order = (last.order + 1) if last else 0
    return PlacementQuestion.objects.create(
        test=test,
        prompt=prompt,
        question_type=question_type,
        options=options,
        correct_answer=correct_answer,
        points=points,
        order=order,
    )


@transaction.atomic
def remove_question(*, question: PlacementQuestion) -> None:
    """Drop a question. Only while the test is DRAFT."""
    if question.test.status != PlacementTest.Status.DRAFT:
        raise UnprocessableEntity(_("Only a draft test can be edited."), code="test_not_draft")
    question.delete()


@transaction.atomic
def submit_for_review(*, test: PlacementTest) -> PlacementTest:
    """DRAFT → PENDING. A test must have at least one question to be reviewable."""
    if test.status != PlacementTest.Status.DRAFT:
        raise UnprocessableEntity(
            _("Only a draft test can be submitted for review."), code="test_not_draft"
        )
    if not test.questions.exists():
        raise UnprocessableEntity(
            _("Add at least one question before submitting."), code="test_has_no_questions"
        )
    test.status = PlacementTest.Status.PENDING
    test.submitted_at = timezone.now()
    test.reject_reason = ""
    test.save(update_fields=["status", "submitted_at", "reject_reason", "updated_at"])
    return test


@transaction.atomic
def approve_test(*, test: PlacementTest, approver) -> PlacementTest:
    """PENDING → APPROVED. Maker-checker: the approver must be a different person
    than the builder. The row is locked so the state + self-check and the write
    can't race a concurrent approval."""
    test = PlacementTest.objects.select_for_update().get(pk=test.pk)
    if test.status != PlacementTest.Status.PENDING:
        raise UnprocessableEntity(
            _("Only a test pending review can be approved."), code="test_not_pending"
        )
    if test.created_by_id is not None and test.created_by_id == approver.id:
        raise PermissionException(
            _("You cannot approve a placement test you built yourself."), code="self_approval"
        )
    test.status = PlacementTest.Status.APPROVED
    test.approved_by = approver
    test.approved_at = timezone.now()
    test.reject_reason = ""
    test.save(update_fields=["status", "approved_by", "approved_at", "reject_reason", "updated_at"])
    return test


@transaction.atomic
def reject_test(*, test: PlacementTest, reviewer, reason: str) -> PlacementTest:
    """PENDING → DRAFT, kicked back to the builder with a reason so it can be fixed
    and re-submitted."""
    test = PlacementTest.objects.select_for_update().get(pk=test.pk)
    if test.status != PlacementTest.Status.PENDING:
        raise UnprocessableEntity(
            _("Only a test pending review can be rejected."), code="test_not_pending"
        )
    test.status = PlacementTest.Status.DRAFT
    test.submitted_at = None
    test.reject_reason = reason
    test.save(update_fields=["status", "submitted_at", "reject_reason", "updated_at"])
    return test


@transaction.atomic
def delete_test(*, test: PlacementTest) -> None:
    """Hard-delete a test. Only a DRAFT may be deleted — a test that is pending or
    approved is an accountability artifact (it carries the checker's sign-off) and
    is never erased unilaterally. The row is locked against a concurrent submit."""
    test = PlacementTest.objects.select_for_update().get(pk=test.pk)
    if test.status != PlacementTest.Status.DRAFT:
        raise UnprocessableEntity(
            _("Only a draft test can be deleted; submit a rejection instead."), code="test_not_draft"
        )
    test.delete()


# ---------------------------------------------------------------------------
# Sitting + auto-grading (F1-5 / F1-6)
# ---------------------------------------------------------------------------


def _level_for(score: int, max_score: int) -> str:
    """Transparent rubric: band by share of the OBJECTIVE points. No objective
    questions (max_score == 0) → no auto-level (a human marks the writing, F8-3)."""
    if max_score <= 0:
        return ""
    pct = score / max_score
    if pct >= 0.7:
        return "advanced"
    if pct >= 0.4:
        return "intermediate"
    return "beginner"


def _validate_response(question: PlacementQuestion, response: Any) -> None:
    """A wrong answer is fine (it scores 0); a wrong-TYPED answer is a clean 400 so
    we never store junk."""

    def bad(msg, code: str):
        return ValidationException(msg, code=code, fields={"question": [str(question.id)]})

    if question.question_type == _QT.TRUE_FALSE:
        if not isinstance(response, bool):
            raise bad(_("Answer true or false."), "answer_not_boolean")
    elif not isinstance(response, str):  # single_choice + writing are text
        raise bad(_("Answer must be text."), "answer_not_text")
    elif question.question_type == _QT.SINGLE_CHOICE and response not in question.options:
        # A wrong answer is fine (it scores 0); an answer that was never an offered
        # option is junk — reject it cleanly, matching the forms engine.
        raise bad(_("Answer must be one of the options."), "answer_not_in_options")


def _grade_answer(question: PlacementQuestion, response: Any) -> tuple[bool | None, int]:
    """(is_correct, awarded_points). Writing is marked by a person later → (None, 0)."""
    if question.question_type not in PlacementQuestion.AUTO_GRADED_TYPES:
        return None, 0
    is_correct = response == question.correct_answer
    return is_correct, (question.points if is_correct else 0)


@transaction.atomic
def assign_test(*, test: PlacementTest, student, assigned_by=None) -> PlacementAttempt:
    """Give an approved test to a prospective student. One attempt per (test, student)."""
    if test.status != PlacementTest.Status.APPROVED:
        raise UnprocessableEntity(
            _("Only an approved test can be assigned."), code="test_not_approved"
        )
    if student.status not in _PROSPECTIVE_STATUSES:
        raise UnprocessableEntity(
            _("Placement tests are only for prospective students."), code="student_not_prospective"
        )
    if PlacementAttempt.objects.filter(test=test, student=student).exists():
        raise ConflictException(
            _("This student already has this placement test."), code="already_assigned"
        )
    try:
        # Savepoint so a racing duplicate hits the unique constraint as a clean 409,
        # not a 500 (mirrors apps/forms submit_response).
        with transaction.atomic():
            return PlacementAttempt.objects.create(test=test, student=student, assigned_by=assigned_by)
    except IntegrityError:
        raise ConflictException(
            _("This student already has this placement test."), code="already_assigned"
        ) from None


@transaction.atomic
def submit_attempt(*, attempt: PlacementAttempt, answers: list[dict]) -> PlacementAttempt:
    """Record + auto-grade a lead's answers, set the level on their profile, and
    freeze the attempt. The row is locked so it can't be double-submitted."""
    attempt = (
        PlacementAttempt.objects.select_for_update()
        .select_related("test", "student")
        .get(pk=attempt.pk)
    )
    if attempt.status != PlacementAttempt.Status.ASSIGNED:
        raise ConflictException(
            _("This placement attempt has already been submitted."), code="already_submitted"
        )
    questions = {q.id: q for q in attempt.test.questions.all()}
    seen: set[int] = set()
    rows: list[PlacementAnswer] = []
    for item in answers:
        qid = item.get("question")
        if not isinstance(qid, int) or qid not in questions:
            raise ValidationException(
                _("Unknown question for this test."),
                code="unknown_question",
                fields={"question": [str(qid)]},
            )
        if qid in seen:
            raise ValidationException(_("Duplicate answer for a question."), code="duplicate_answer")
        seen.add(qid)
        question = questions[qid]
        response = item.get("response")
        _validate_response(question, response)
        is_correct, awarded = _grade_answer(question, response)
        rows.append(
            PlacementAnswer(
                attempt=attempt,
                question=question,
                response=response,
                is_correct=is_correct,
                awarded_points=awarded,
            )
        )
    PlacementAnswer.objects.bulk_create(rows)
    max_score = sum(
        q.points for q in questions.values() if q.question_type in PlacementQuestion.AUTO_GRADED_TYPES
    )
    score = sum(r.awarded_points for r in rows)
    attempt.score = score
    attempt.max_score = max_score
    attempt.level = _level_for(score, max_score)
    attempt.status = PlacementAttempt.Status.GRADED
    attempt.submitted_at = timezone.now()
    attempt.save(update_fields=["score", "max_score", "level", "status", "submitted_at", "updated_at"])
    # F1-6: the auto-level lands on the lead's profile immediately.
    if attempt.level:
        attempt.student.academic_level = attempt.level
        attempt.student.save(update_fields=["academic_level", "updated_at"])
    return attempt
