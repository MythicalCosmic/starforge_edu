"""Academics write services (TASKS §11, TD-13/14).

Exam results upsert with a `grade_changed` audit signal on overwrite; CSV import
is all-or-nothing; `compute_term_grade` rolls published results into a weighted
0-100 `Grade` rendered per the Center's scheme; transcripts are generated
off-request (weasyprint → S3) by `generate_transcript`. Emit-only — no audit
write or notification dispatch here (D3-D consumes `grade_changed`).
"""

from __future__ import annotations

import csv
import io
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academics.grading import display_for
from apps.academics.models import Exam, ExamResult, Grade, Transcript
from apps.academics.signals import grade_changed
from apps.cohorts.models import CohortMembership
from apps.org.selectors import get_center_settings
from apps.students.models import StudentProfile
from core.exceptions import UnprocessableEntity, ValidationException
from core.utils import current_schema
from infrastructure.storage.s3_client import presign_download, upload_bytes

_HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Exam results
# ---------------------------------------------------------------------------


def _emit_grade_changed(result: ExamResult, old_score, new_score, actor, schema: str) -> None:
    transaction.on_commit(
        lambda: grade_changed.send(
            sender=ExamResult,
            instance=result,
            old_score=old_score,
            new_score=new_score,
            actor_id=getattr(actor, "id", None),
            schema_name=schema,
        )
    )


@transaction.atomic
def record_results(*, exam: Exam, rows: list[dict], actor=None) -> dict:
    """Upsert `[{student, score, note?}]` for `exam`. Scores outside
    `0..max_score` abort the whole batch with **422**. Overwriting an existing
    result with a DIFFERENT score emits `grade_changed` exactly once (never on
    first entry, and never when the score is unchanged)."""
    field_errors: dict[str, list[str]] = {}
    for index, row in enumerate(rows):
        score = row["score"]
        if score < 0 or score > exam.max_score:
            field_errors[str(index)] = [f"Score must be between 0 and {exam.max_score} (got {score})."]
    if field_errors:
        raise UnprocessableEntity(
            _("One or more scores are out of range."), code="score_out_of_range", fields=field_errors
        )

    schema = current_schema()
    created = updated = 0
    results: list[ExamResult] = []
    for row in rows:
        student = row["student"]
        existing = ExamResult.objects.filter(exam=exam, student=student).first()
        old_score = existing.score if existing else None
        result, was_created = ExamResult.objects.update_or_create(
            exam=exam,
            student=student,
            defaults={"score": row["score"], "note": row.get("note", ""), "graded_by": actor},
        )
        created += int(was_created)
        updated += int(not was_created)
        results.append(result)
        # Only emit on an actual change — re-entering an identical score is a
        # no-op and must not produce audit churn (D3-D consumes grade_changed).
        if not was_created and old_score != result.score:
            _emit_grade_changed(result, old_score, result.score, actor, schema)
    return {"created": created, "updated": updated, "results": results}


@transaction.atomic
def bulk_grade_import(*, exam: Exam, csv_file, actor=None) -> dict:
    """Parse a `student_id,score,note?` CSV and record every row, or **422** with
    per-row errors and **zero rows written** if any row is invalid (DoD)."""
    raw = csv_file.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))
    if not {"student_id", "score"} <= set(reader.fieldnames or []):
        raise ValidationException(
            _("CSV must have at least 'student_id' and 'score' columns."), code="bad_csv_header"
        )

    rows: list[dict] = []
    row_errors: list[dict] = []
    for line_no, raw_row in enumerate(reader, start=2):  # line 1 is the header
        code = (raw_row.get("student_id") or "").strip()
        student = StudentProfile.objects.filter(student_id=code).first()
        if student is None:
            row_errors.append({"row": line_no, "error": f"Unknown student_id '{code}'."})
            continue
        try:
            score = Decimal((raw_row.get("score") or "").strip())
        except (InvalidOperation, ValueError):
            row_errors.append({"row": line_no, "error": "Score is not a number."})
            continue
        if score < 0 or score > exam.max_score:
            row_errors.append({"row": line_no, "error": f"Score out of range 0..{exam.max_score}."})
            continue
        rows.append({"student": student, "score": score, "note": (raw_row.get("note") or "").strip()})

    if row_errors:
        raise UnprocessableEntity(
            _("CSV has invalid rows; nothing was imported."),
            code="csv_row_errors",
            fields={"rows": row_errors},
        )
    return record_results(exam=exam, rows=rows, actor=actor)


def publish_exam(*, exam: Exam, actor=None) -> Exam:
    if not exam.is_published:
        exam.is_published = True
        exam.published_at = timezone.now()
        exam.save(update_fields=["is_published", "published_at"])
    return exam


# ---------------------------------------------------------------------------
# Term grades
# ---------------------------------------------------------------------------


def compute_term_grade(*, student, subject, term, settings=None, publish: bool = False) -> Grade | None:
    """Weighted 0-100 term grade from **published** exam results:
    `100 * sum(score/max * weight) / sum(weight)`. Returns None when nothing
    published contributes. Writes/updates the `Grade` with a `components`
    breakdown and a scheme-rendered `value_display`."""
    settings = settings or get_center_settings()
    results = ExamResult.objects.filter(
        student=student, exam__subject=subject, exam__term=term, exam__is_published=True
    ).select_related("exam")

    total_weight = Decimal("0")
    acc = Decimal("0")
    components: list[dict] = []
    for result in results:
        exam = result.exam
        max_score = exam.max_score or Decimal("0")
        weight = exam.weight
        fraction = (result.score / max_score) if max_score else Decimal("0")
        acc += fraction * weight
        total_weight += weight
        components.append(
            {
                "exam": exam.id,
                "title": exam.title,
                "score": str(result.score),
                "max_score": str(max_score),
                "weight": str(weight),
            }
        )
    if total_weight == 0:
        return None

    value_raw = (_HUNDRED * acc / total_weight).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    defaults: dict = {
        "value_raw": value_raw,
        "value_display": display_for(value_raw, settings.grading_scheme),
        "components": components,
    }
    if publish:
        defaults["is_published"] = True
        defaults["published_at"] = timezone.now()
    grade, _created = Grade.objects.update_or_create(
        student=student, subject=subject, term=term, defaults=defaults
    )
    return grade


def recompute_cohort_term(*, cohort, subject, term, publish: bool = False) -> list[Grade]:
    """Recompute every active member's grade for (subject, term)."""
    settings = get_center_settings()
    student_ids = CohortMembership.objects.filter(cohort=cohort, end_date__isnull=True).values_list(
        "student_id", flat=True
    )
    grades: list[Grade] = []
    for student in StudentProfile.objects.filter(pk__in=list(student_ids)):
        grade = compute_term_grade(
            student=student, subject=subject, term=term, settings=settings, publish=publish
        )
        if grade is not None:
            grades.append(grade)
    return grades


# ---------------------------------------------------------------------------
# Transcripts (TD-14: weasyprint → S3, off-request)
# ---------------------------------------------------------------------------


@transaction.atomic
def request_transcript(*, student, term=None, requested_by=None) -> Transcript:
    """Create a pending Transcript and enqueue PDF generation after commit."""
    transcript = Transcript.objects.create(student=student, term=term, requested_by=requested_by)
    schema = current_schema()
    transaction.on_commit(lambda: _enqueue_transcript(transcript.pk, schema))
    return transcript


def _enqueue_transcript(transcript_id: int, schema: str) -> None:
    from celery_tasks.academics_tasks import generate_transcript_pdf

    generate_transcript_pdf.delay(transcript_id, _schema_name=schema)


def render_transcript_pdf(transcript: Transcript) -> bytes:
    """Render the transcript HTML to PDF bytes. weasyprint is imported lazily so
    the app loads where its GTK native libs are absent (e.g. a Windows dev box);
    only this call needs them."""
    from django.template.loader import render_to_string
    from django.utils import translation
    from weasyprint import HTML  # lazy on purpose: GTK native libs only needed here

    student = transcript.student
    lang = getattr(student.user, "preferred_language", "en")
    grades = (
        Grade.objects.filter(student=student, is_published=True)
        .select_related("subject", "term")
        .order_by("subject__name")
    )
    if transcript.term_id:
        grades = grades.filter(term_id=transcript.term_id)
    with translation.override(lang):
        html = render_to_string(
            "documents/transcript.html",
            {"transcript": transcript, "student": student, "grades": grades},
        )
    return HTML(string=html).write_pdf()


def generate_transcript(transcript_id: int) -> str:
    """Idempotent task body: pending → processing → done, uploading the PDF to
    `{schema}/transcripts/{id}.pdf`. A `done` transcript short-circuits (re-run
    safe). Runs under the active tenant schema."""
    transcript = Transcript.objects.select_related("student__user", "term").get(pk=transcript_id)
    if transcript.status == Transcript.Status.DONE:
        return transcript.pdf_key

    transcript.status = Transcript.Status.PROCESSING
    transcript.save(update_fields=["status"])

    pdf = render_transcript_pdf(transcript)
    key = f"{current_schema()}/transcripts/{transcript.pk}.pdf"
    upload_bytes(key, pdf, content_type="application/pdf")

    transcript.pdf_key = key
    transcript.status = Transcript.Status.DONE
    transcript.generated_at = timezone.now()
    transcript.save(update_fields=["pdf_key", "status", "generated_at"])
    return key


def mark_transcript_failed(transcript_id: int, exc: Exception) -> None:
    Transcript.objects.filter(pk=transcript_id).update(status=Transcript.Status.FAILED, error=str(exc)[:2000])


def presign_transcript(transcript: Transcript) -> str | None:
    if transcript.status == Transcript.Status.DONE and transcript.pdf_key:
        return presign_download(transcript.pdf_key, expires_in=600)
    return None
