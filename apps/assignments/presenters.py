"""Assignment-domain presenters — plain dict mappers (replace the DRF serializers)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.assignments.models import Assignment, Submission, SubmissionGrade

_CENTS = Decimal("0.01")


def _money(value) -> str | None:
    # Match DRF's DecimalField(decimal_places=2) string output ("100.00").
    return str(value.quantize(_CENTS)) if value is not None else None


def assignment_to_dict(a: Assignment) -> dict[str, Any]:
    return {
        "id": a.id,
        "cohort": a.cohort_id,
        "title": a.title,
        "description": a.description,
        "due_at": a.due_at.isoformat() if a.due_at else None,
        "attachments": a.attachments,
        "rubric": a.rubric,
        "max_score": _money(a.max_score),
        "max_resubmits": a.max_resubmits,
        "status": a.status,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "created_at": a.created_at.isoformat(),
    }


def grade_to_dict(g: SubmissionGrade) -> dict[str, Any]:
    return {
        "submission": g.submission_id,
        "score": _money(g.score),
        "rubric_scores": g.rubric_scores,
        "feedback": g.feedback,
        "ai_feedback": g.ai_feedback,
        "graded_by": g.graded_by_id,
        "graded_at": g.graded_at.isoformat() if g.graded_at else None,
    }


def submission_to_dict(s: Submission) -> dict[str, Any]:
    try:
        grade = grade_to_dict(s.grade)
    except SubmissionGrade.DoesNotExist:
        grade = None
    return {
        "id": s.id,
        "assignment": s.assignment_id,
        "student": s.student_id,
        "text": s.text,
        "attachments": s.attachments,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "is_late": s.is_late,
        "attempt_number": s.attempt_number,
        "status": s.status,
        "grade": grade,
    }
