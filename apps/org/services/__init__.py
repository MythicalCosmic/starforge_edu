"""Branch / Department / org write services."""

from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.org.models import Branch, BranchTransfer, BranchWorkingHours, Department
from core.exceptions import ConflictException, ValidationException

# Enrollment states that still occupy capacity (mirrors Lane D's StudentProfile).
ACTIVE_STUDENT_STATUSES_EXCLUDED = ("graduated", "withdrawn")


def _teacher_profile_model():
    try:
        return django_apps.get_model("teachers", "TeacherProfile")
    except LookupError:  # Lane D hasn't landed yet — validation no-ops.
        return None


def _student_profile_model():
    try:
        return django_apps.get_model("students", "StudentProfile")
    except LookupError:
        return None


def validate_department_head(user, *, branch_id: int | None = None) -> None:
    """Raise unless `user` may head a department (must have a TeacherProfile).

    Single source of truth for D1-LF-4 / D1-LD-10 — shared by the service and
    DepartmentSerializer.validate_head. Once `teachers.TeacherProfile` exists
    the user must have one; until then the check is skipped."""
    if user is None:
        return
    TeacherProfile = _teacher_profile_model()
    if TeacherProfile is not None:
        teacher = TeacherProfile.objects.filter(user=user).first()
        if teacher is None:
            raise ValidationException(_("Department head must be a teacher."), code="head_not_teacher")
        if branch_id is not None and teacher.branch_id != branch_id:
            raise ValidationException(
                _("Department head must teach at the department's branch."),
                code="head_branch_mismatch",
                fields={"head": ["Teacher belongs to a different branch."]},
            )


def set_department_head(department: Department, user) -> Department:
    """Assign a department head (validated: head must be a teacher)."""
    validate_department_head(user, branch_id=department.branch_id)
    department.head = user
    department.save(update_fields=["head", "updated_at"])
    return department


def validate_student_id_pattern(pattern: str, *, center_code: str = "") -> None:
    """Guard `CenterSettings.student_id_pattern` (D1-LD-4): it must contain
    {NNNNN} (otherwise generated IDs collide → IntegrityError 500) and a
    rendered sample must fit the 32-char `student_id` column. {YYYY} is
    recommended so the per-year counter reset never collides; its absence is
    not an error (the counter is year-scoped but historic IDs may overlap)."""
    if "{NNNNN}" not in pattern:
        raise ValidationException(
            _("student_id_pattern must contain the {NNNNN} counter placeholder."),
            code="invalid_id_pattern",
        )
    sample = (
        pattern.replace("{CODE}", center_code or "X" * 16)
        .replace("{YYYY}", "2026")
        .replace("{NNNNN}", "00000")
    )
    if len(sample) > 32:  # StudentProfile.student_id max_length
        raise ValidationException(
            _("student_id_pattern renders longer than 32 characters."),
            code="invalid_id_pattern",
        )


@transaction.atomic
def replace_working_hours(branch: Branch, rows: list[dict[str, Any]]) -> list[BranchWorkingHours]:
    """Replace a branch's weekday rows wholesale (D1-LF-2). Validates that open
    times precede close times on non-closed days and that no weekday repeats."""
    weekdays = [row["weekday"] for row in rows]
    if len(weekdays) != len(set(weekdays)):
        raise ValidationException(_("Each weekday may appear at most once."), code="invalid_working_hours")
    for row in rows:
        if not row.get("is_closed", False) and row["opens_at"] >= row["closes_at"]:
            raise ValidationException(_("opens_at must be before closes_at."), code="invalid_working_hours")
    BranchWorkingHours.objects.filter(branch=branch).delete()
    BranchWorkingHours.objects.bulk_create(
        [
            BranchWorkingHours(
                branch=branch,
                weekday=row["weekday"],
                opens_at=row["opens_at"],
                closes_at=row["closes_at"],
                is_closed=row.get("is_closed", False),
            )
            for row in rows
        ]
    )
    return list(BranchWorkingHours.objects.filter(branch=branch).order_by("weekday"))


def archive_branch(branch: Branch) -> Branch:
    """Soft-delete a branch (D1-LF-7). Refuses while it still has active
    students (no-op until Lane D's StudentProfile exists)."""
    StudentProfile = _student_profile_model()
    if StudentProfile is not None:
        has_active = (
            StudentProfile.objects.filter(branch=branch)
            .exclude(status__in=ACTIVE_STUDENT_STATUSES_EXCLUDED)
            .exists()
        )
        if has_active:
            raise ConflictException(_("Branch still has active students."), code="branch_has_active_students")
    branch.archived_at = timezone.now()
    branch.is_active = False
    branch.save(update_fields=["archived_at", "is_active", "updated_at"])
    return branch


def record_transfer(
    *,
    user,
    from_branch: Branch,
    to_branch: Branch,
    reason: str = "",
    actor=None,
) -> BranchTransfer:
    """Record a branch transfer (history only; the cascade is a Day-2 concern)."""
    return BranchTransfer.objects.create(
        user=user, from_branch=from_branch, to_branch=to_branch, reason=reason, actor=actor
    )
