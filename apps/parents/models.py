"""Parent domain: ParentProfile + Guardian link to students.

A parent only ever sees data for students they are linked to via Guardian
(visibility scoping is enforced in the viewsets, not here).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class ParentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parent_profile"
    )
    occupation = models.CharField(max_length=200, blank=True)
    workplace = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Parent: {self.user}"


class Guardian(models.Model):
    """Links a parent to a student with a relationship type.

    Exactly one guardian per student should be primary (enforced in service /
    serializer logic, plus a partial unique index below).
    """

    class Relationship(models.TextChoices):
        MOTHER = "mother", "Mother"
        FATHER = "father", "Father"
        GRANDPARENT = "grandparent", "Grandparent"
        LEGAL_GUARDIAN = "legal_guardian", "Legal guardian"
        OTHER = "other", "Other"

    parent = models.ForeignKey(ParentProfile, on_delete=models.CASCADE, related_name="guardianships")
    student = models.ForeignKey("students.StudentProfile", on_delete=models.CASCADE, related_name="guardians")
    relationship = models.CharField(max_length=20, choices=Relationship.choices)
    is_primary = models.BooleanField(default=False)
    can_pickup = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("parent", "student"), name="unique_parent_student"),
            models.UniqueConstraint(
                fields=("student",),
                condition=models.Q(is_primary=True),
                name="one_primary_guardian_per_student",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.parent.user} -> {self.student.student_id} ({self.relationship})"
