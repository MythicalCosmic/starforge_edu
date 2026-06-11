"""Student write services: creation, the enrollment state machine, generated
IDs, and CSV import (TASKS §5)."""

from __future__ import annotations

import csv
import io
import itertools
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.org.selectors import get_center_settings
from apps.org.services import validate_student_id_pattern
from apps.students.models import EnrollmentEvent, StudentIdCounter, StudentProfile
from apps.users.services import resolve_or_create_user
from core.exceptions import ValidationException
from core.utils import current_schema

# Enrollment state machine (D1-LD-3). Terminal: graduated. withdrawn re-enrolls.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    StudentProfile.Status.LEAD: {StudentProfile.Status.APPLICATION},
    StudentProfile.Status.APPLICATION: {StudentProfile.Status.ACCEPTED},
    StudentProfile.Status.ACCEPTED: {StudentProfile.Status.ENROLLED},
    StudentProfile.Status.ENROLLED: {StudentProfile.Status.ACTIVE},
    StudentProfile.Status.ACTIVE: {
        StudentProfile.Status.GRADUATED,
        StudentProfile.Status.WITHDRAWN,
    },
    StudentProfile.Status.GRADUATED: set(),
    StudentProfile.Status.WITHDRAWN: {StudentProfile.Status.APPLICATION},
}

# Canonical forward path used to synthesize event history when a student is
# created directly at a later status (convenience kept for seed/import flows).
_CANONICAL_PATH = (
    StudentProfile.Status.LEAD,
    StudentProfile.Status.APPLICATION,
    StudentProfile.Status.ACCEPTED,
    StudentProfile.Status.ENROLLED,
    StudentProfile.Status.ACTIVE,
)

# Statuses at/past 'enrolled' — creation at these sets enrollment_date.
_ENROLLED_OR_LATER = {
    StudentProfile.Status.ENROLLED,
    StudentProfile.Status.ACTIVE,
    StudentProfile.Status.GRADUATED,
    StudentProfile.Status.WITHDRAWN,
}


def _creation_status_chain(status: str) -> list[str]:
    """The lead→…→status chain implied by creating a student at `status`."""
    if status == StudentProfile.Status.LEAD:
        return []
    if status in (StudentProfile.Status.GRADUATED, StudentProfile.Status.WITHDRAWN):
        return [*_CANONICAL_PATH, status]
    return list(_CANONICAL_PATH[: _CANONICAL_PATH.index(status) + 1])


@transaction.atomic
def generate_student_id() -> str:
    """Render the Center's `student_id_pattern`, advancing a year-scoped counter
    under a row lock so concurrent creates never collide (D1-LD-4)."""
    settings_obj = get_center_settings()
    code = settings_obj.center_code or current_schema().upper()
    # Defensive re-check: the pattern is validated on CenterSettings writes, but
    # a bad row (e.g. seeded directly) must 400, not IntegrityError-500.
    validate_student_id_pattern(settings_obj.student_id_pattern, center_code=code)
    year = timezone.now().year
    counter, _created = StudentIdCounter.objects.select_for_update().get_or_create(year=year)
    counter.last_value += 1
    counter.save(update_fields=["last_value"])
    return (
        settings_obj.student_id_pattern.replace("{CODE}", code)
        .replace("{YYYY}", str(year))
        .replace("{NNNNN}", f"{counter.last_value:05d}")
    )


@transaction.atomic
def create_student(
    *,
    branch,
    phone: str = "",
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    status: str = StudentProfile.Status.LEAD,
    academic_level: str = "",
    medical_notes: str = "",
    emergency_contacts: list | None = None,
) -> StudentProfile:
    user = resolve_or_create_user(
        phone=phone,
        email=email,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
    )
    if StudentProfile.objects.filter(user=user).exists():
        raise ValidationException(_("This person already has a student profile."), code="duplicate_student")
    student = StudentProfile.objects.create(
        user=user,
        branch=branch,
        student_id=generate_student_id(),
        status=status,
        enrollment_date=timezone.now().date() if status in _ENROLLED_OR_LATER else None,
        academic_level=academic_level,
        medical_notes=medical_notes,
        emergency_contacts=emergency_contacts or [],
    )
    # Creation at a later status writes the synthetic event chain so the
    # D1-LD-3 invariants (event history + enrollment_date) hold from birth.
    chain = _creation_status_chain(status)
    EnrollmentEvent.objects.bulk_create(
        EnrollmentEvent(
            student=student,
            from_status=from_status,
            to_status=to_status,
            note=f"auto: created at status '{status}'",
        )
        for from_status, to_status in itertools.pairwise(chain)
    )
    return student


@transaction.atomic
def transition_enrollment(
    *, student: StudentProfile, to_status: str, reason_code: str = "", note: str = "", actor=None
) -> StudentProfile:
    from_status = student.status
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise ValidationException(
            _("Cannot move from %(from)s to %(to)s.") % {"from": from_status, "to": to_status},
            code="invalid_transition",
        )
    student.status = to_status
    fields = ["status", "updated_at"]
    if to_status == StudentProfile.Status.ENROLLED and student.enrollment_date is None:
        student.enrollment_date = timezone.now().date()
        fields.append("enrollment_date")
    student.save(update_fields=fields)
    EnrollmentEvent.objects.create(
        student=student,
        from_status=from_status,
        to_status=to_status,
        reason_code=reason_code,
        note=note,
        actor=actor,
    )
    return student


def import_students_csv(*, file_obj, branch) -> dict[str, Any]:
    """Create one user+profile per CSV row inside a savepoint so a bad row never
    aborts the valid ones (D1-LD-5). Columns: phone, email, first_name, last_name."""
    settings_obj = get_center_settings()
    max_bytes = settings_obj.max_upload_mb * 1024 * 1024
    size = getattr(file_obj, "size", None)
    if size is not None and size > max_bytes:
        raise ValidationException(
            _("File exceeds the maximum upload size of %(mb)s MB.") % {"mb": settings_obj.max_upload_mb},
            code="file_too_large",
        )
    content = file_obj.read()
    if isinstance(content, bytes):
        try:
            # utf-8-sig strips Excel's BOM and is a no-op for BOM-less UTF-8.
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationException(_("File must be UTF-8 encoded."), code="invalid_encoding") from None
    reader = csv.DictReader(io.StringIO(content))
    created = 0
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(reader, start=1):
        try:
            with transaction.atomic():
                create_student(
                    branch=branch,
                    phone=(row.get("phone") or "").strip(),
                    email=(row.get("email") or "").strip(),
                    first_name=(row.get("first_name") or "").strip(),
                    last_name=(row.get("last_name") or "").strip(),
                )
            created += 1
        except ValidationException as exc:
            errors.append({"row": index, "detail": str(exc.detail)})
        except Exception as exc:  # malformed row data
            errors.append({"row": index, "detail": str(exc)})
    return {"created": created, "errors": errors}
