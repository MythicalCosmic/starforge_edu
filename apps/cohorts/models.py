"""Cohorts: class groups, their student memberships, and co-teachers."""

from __future__ import annotations

from django.db import models


class Cohort(models.Model):
    branch = models.ForeignKey("org.Branch", on_delete=models.PROTECT, related_name="cohorts")
    department = models.ForeignKey(
        "org.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="cohorts"
    )
    primary_teacher = models.ForeignKey(
        "teachers.TeacherProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_cohorts",
    )

    name = models.CharField(max_length=200)
    level = models.CharField(max_length=120, blank=True)
    capacity = models.PositiveIntegerField(default=0)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("branch", "is_archived"))]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class CohortMembership(models.Model):
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="memberships")
    student = models.ForeignKey(
        "students.StudentProfile", on_delete=models.CASCADE, related_name="cohort_memberships"
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("cohort", "student"), name="unique_cohort_student")]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.student_id} in {self.cohort_id}"


class CohortTeacher(models.Model):
    """Co-teacher assignment (the lead is Cohort.primary_teacher)."""

    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="co_teachers")
    teacher = models.ForeignKey(
        "teachers.TeacherProfile", on_delete=models.CASCADE, related_name="co_teaching"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("cohort", "teacher"), name="unique_cohort_teacher")]
