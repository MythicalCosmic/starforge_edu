"""Teacher domain: TeacherProfile (one per User who teaches at the center)."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class TeacherProfile(models.Model):
    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full time"
        PART_TIME = "part_time", "Part time"
        CONTRACT = "contract", "Contract"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teacher_profile"
    )
    department = models.ForeignKey(
        "org.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="teachers"
    )

    hire_date = models.DateField(null=True, blank=True)
    employment_type = models.CharField(
        max_length=16, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    subjects = models.JSONField(default=list, blank=True)
    qualifications = models.TextField(blank=True)

    # Fair-payroll vision: a teacher's share (%) of payments from their students.
    # The full payout-rules engine comes later (see docs/PRODUCT_VISION.md §7);
    # this default lives here so payroll has something to read.
    payout_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hourly_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"Teacher: {self.user}"
