"""Teacher write services (TASKS §7)."""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.teachers.models import TeacherProfile
from apps.users.services import resolve_or_create_user
from core.exceptions import ValidationException


@transaction.atomic
def create_teacher(
    *,
    branch,
    department=None,
    phone: str = "",
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    hire_date=None,
    subjects: list | None = None,
    qualifications: str = "",
    salary_type: str = TeacherProfile.SalaryType.MONTHLY,
    rate=None,
    is_substitute: bool = False,
) -> TeacherProfile:
    if department is not None and department.branch_id != branch.id:
        raise ValidationException(
            _("Department must belong to the teacher's branch."), code="department_branch_mismatch"
        )
    user = resolve_or_create_user(
        phone=phone, email=email, first_name=first_name, last_name=last_name, middle_name=middle_name
    )
    if TeacherProfile.objects.filter(user=user).exists():
        raise ValidationException(_("This person already has a teacher profile."), code="duplicate_teacher")
    return TeacherProfile.objects.create(
        user=user,
        branch=branch,
        department=department,
        hire_date=hire_date,
        subjects=subjects or [],
        qualifications=qualifications,
        salary_type=salary_type,
        rate=rate,
        is_substitute=is_substitute,
    )
