"""Branch / Department / org write services."""

from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.exceptions import ConflictException, ValidationException

from .models import Branch, BranchTransfer, BranchWorkingHours, Department

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


def set_department_head(department: Department, user) -> Department:
    """Assign a department head. Once `teachers.TeacherProfile` exists the user
    must have one; until then the check is skipped (D1-LF-4 / D1-LD-10)."""
    if user is not None:
        TeacherProfile = _teacher_profile_model()
        if TeacherProfile is not None and not TeacherProfile.objects.filter(user=user).exists():
            raise ValidationException(_("Department head must be a teacher."), code="head_not_teacher")
    department.head = user
    department.save(update_fields=["head", "updated_at"])
    return department


@transaction.atomic
def replace_working_hours(branch: Branch, rows: list[dict[str, Any]]) -> list[BranchWorkingHours]:
    """Replace a branch's weekday rows wholesale (D1-LF-2). Validates that open
    times precede close times on non-closed days."""
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
