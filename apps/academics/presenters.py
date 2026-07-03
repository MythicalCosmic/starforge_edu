"""Academics response presenters (the DRF serializer output shapes)."""

from __future__ import annotations

from decimal import Decimal

from apps.academics.models import Exam, ExamResult, Grade, Subject, Transcript


def _dec(value, places: int) -> str:
    """Render a Decimal as a fixed-places string, matching DRF DecimalField."""
    return str(Decimal(value).quantize(Decimal(1).scaleb(-places)))


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def subject_to_dict(subject: Subject) -> dict:
    return {
        "id": subject.id,
        "name": subject.name,
        "code": subject.code,
        "department": subject.department_id,
        "description": subject.description,
        "is_active": subject.is_active,
    }


def exam_to_dict(exam: Exam) -> dict:
    return {
        "id": exam.id,
        "subject": exam.subject_id,
        "cohort": exam.cohort_id,
        "term": exam.term_id,
        "type": exam.type,
        "title": exam.title,
        "exam_date": exam.exam_date.isoformat(),
        "max_score": _dec(exam.max_score, 2),
        "weight": _dec(exam.weight, 3),
        "is_published": exam.is_published,
        "published_at": _iso(exam.published_at),
    }


def exam_result_to_dict(result: ExamResult) -> dict:
    return {
        "id": result.id,
        "exam": result.exam_id,
        "student": result.student_id,
        "student_name": result.student.user.get_full_name(),
        "score": _dec(result.score, 2),
        "note": result.note,
        "graded_by": result.graded_by_id,
        "graded_at": _iso(result.graded_at),
    }


def grade_to_dict(grade: Grade) -> dict:
    return {
        "id": grade.id,
        "student": grade.student_id,
        "student_name": grade.student.user.get_full_name(),
        "subject": grade.subject_id,
        "subject_name": grade.subject.name,
        "term": grade.term_id,
        "value_raw": _dec(grade.value_raw, 3),
        "value_display": grade.value_display,
        "components": grade.components,
        "is_published": grade.is_published,
        "published_at": _iso(grade.published_at),
        "computed_at": _iso(grade.computed_at),
    }


def transcript_to_dict(transcript: Transcript) -> dict:
    from apps.academics.services import presign_transcript

    return {
        "id": transcript.id,
        "student": transcript.student_id,
        "term": transcript.term_id,
        "status": transcript.status,
        "download_url": presign_transcript(transcript),
        "error": transcript.error,
        "generated_at": _iso(transcript.generated_at),
        "created_at": _iso(transcript.created_at),
    }
