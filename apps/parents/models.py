"""Parent / guardian domain models (TASKS §6).

`Guardian` is THE sanctioned parents→students link (a documented exception to
the no-cross-role-FK rule, per docs/adding-an-app.md routing note).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class ParentProfile(models.Model):
    user = models.OneToOneField("users.User", on_delete=models.CASCADE, related_name="parent_profile")
    workplace = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"parent#{self.user_id}"


class Guardian(models.Model):
    class Relationship(models.TextChoices):
        MOTHER = "mother", _("Mother")
        FATHER = "father", _("Father")
        GRANDPARENT = "grandparent", _("Grandparent")
        LEGAL_GUARDIAN = "legal_guardian", _("Legal guardian")
        OTHER = "other", _("Other")

    parent = models.ForeignKey(ParentProfile, on_delete=models.CASCADE, related_name="guardianships")
    student = models.ForeignKey("students.StudentProfile", on_delete=models.CASCADE, related_name="guardians")
    relationship = models.CharField(max_length=16, choices=Relationship.choices)
    is_primary = models.BooleanField(default=False)
    custody_notes = models.TextField(blank=True)

    class Meta:
        unique_together = (("parent", "student"),)
        ordering = ("student", "-is_primary")
        constraints = [
            models.UniqueConstraint(
                fields=["student"],
                condition=Q(is_primary=True),
                name="one_primary_guardian_per_student",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.parent_id}->{self.student_id}"


class PickupAuthorization(models.Model):
    student = models.ForeignKey(
        "students.StudentProfile", on_delete=models.CASCADE, related_name="pickup_authorizations"
    )
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=32)
    relationship = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.student_id}:{self.full_name}"
