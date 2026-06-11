"""Teacher read selectors."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.teachers.models import TeacherProfile


def list_teachers() -> QuerySet[TeacherProfile]:
    return TeacherProfile.objects.select_related("user", "branch", "department")
