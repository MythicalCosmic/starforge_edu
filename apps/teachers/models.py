"""Teacher domain models (TASKS §7)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class TeacherProfile(models.Model):
    class SalaryType(models.TextChoices):
        HOURLY = "hourly", _("Hourly")
        MONTHLY = "monthly", _("Monthly")

    user = models.OneToOneField("users.User", on_delete=models.CASCADE, related_name="teacher_profile")
    branch = models.ForeignKey("org.Branch", on_delete=models.PROTECT, related_name="teachers")
    department = models.ForeignKey(
        "org.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teachers",
    )
    hire_date = models.DateField(null=True, blank=True)
    subjects = models.JSONField(default=list, blank=True)
    qualifications = models.TextField(blank=True)
    salary_type = models.CharField(max_length=8, choices=SalaryType.choices, default=SalaryType.MONTHLY)
    rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_substitute = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"teacher#{self.user_id}"
