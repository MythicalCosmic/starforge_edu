"""Schedule: lessons (incl. recurring occurrences) and holidays.

Recurring lessons are materialized as individual Lesson rows sharing a
``series_id`` so a single occurrence can be cancelled/moved independently.
Conflict detection (room / teacher / cohort) lives in services.py.
"""

from __future__ import annotations

from django.db import models


class Holiday(models.Model):
    """A non-teaching day. branch=null means center-wide."""

    branch = models.ForeignKey(
        "org.Branch", on_delete=models.CASCADE, null=True, blank=True, related_name="holidays"
    )
    date = models.DateField()
    name = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("branch", "date"), name="unique_branch_holiday")]
        ordering = ("date",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.date} {self.name}"


class Lesson(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CANCELLED = "cancelled", "Cancelled"
        DONE = "done", "Done"

    cohort = models.ForeignKey("cohorts.Cohort", on_delete=models.CASCADE, related_name="lessons")
    # Denormalized from cohort for fast conflict queries + object scoping.
    branch = models.ForeignKey("org.Branch", on_delete=models.CASCADE, related_name="lessons")
    room = models.ForeignKey(
        "org.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons"
    )
    teacher = models.ForeignKey(
        "teachers.TeacherProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lessons",
    )

    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    series_id = models.UUIDField(null=True, blank=True, db_index=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("start",)
        indexes = [
            models.Index(fields=("room", "start", "end")),
            models.Index(fields=("teacher", "start", "end")),
            models.Index(fields=("cohort", "start", "end")),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.cohort_id} {self.start:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        # Keep branch consistent with the cohort it belongs to.
        if self.cohort_id and not self.branch_id:
            self.branch_id = self.cohort.branch_id
        super().save(*args, **kwargs)
