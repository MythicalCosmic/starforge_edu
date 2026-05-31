"""Student domain: StudentProfile (one per User who studies at the center)."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class StudentProfile(models.Model):
    """Enrollment record for a learner. Branch-scoped for object permissions."""

    class Status(models.TextChoices):
        LEAD = "lead", "Lead"
        APPLICANT = "applicant", "Applicant"
        ACCEPTED = "accepted", "Accepted"
        ENROLLED = "enrolled", "Enrolled"
        ACTIVE = "active", "Active"
        GRADUATED = "graduated", "Graduated"
        WITHDRAWN = "withdrawn", "Withdrawn"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile"
    )
    branch = models.ForeignKey("org.Branch", on_delete=models.PROTECT, related_name="students")

    # Center-unique human ID, e.g. "2026-00042" (see services.generate_student_id).
    student_id = models.CharField(max_length=32, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.LEAD)

    enrollment_date = models.DateField(null=True, blank=True)
    academic_level = models.CharField(max_length=120, blank=True)
    # TODO(Premium): field-level encryption for medical_notes (see TASKS §25).
    medical_notes = models.TextField(blank=True)
    emergency_contacts = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status",)),
            models.Index(fields=("branch", "status")),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.student_id} ({self.user})"
