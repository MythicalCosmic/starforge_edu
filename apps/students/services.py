"""Student write-side services."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import StudentProfile


@transaction.atomic
def generate_student_id() -> str:
    """Center-unique human ID: ``<year>-<5-digit sequence>`` (e.g. 2026-00042).

    Sequence is per-year, per-tenant (the query runs inside the active schema).
    Locks matching rows to avoid duplicate IDs under concurrent enrollment.
    """

    prefix = f"{timezone.now().year}-"
    last = (
        StudentProfile.objects.select_for_update()
        .filter(student_id__startswith=prefix)
        .order_by("-student_id")
        .first()
    )
    seq = 1
    if last is not None:
        try:
            seq = int(last.student_id.split("-", 1)[1]) + 1
        except (IndexError, ValueError):
            seq = StudentProfile.objects.filter(student_id__startswith=prefix).count() + 1
    return f"{prefix}{seq:05d}"
